"""
Tests for create_pr_from_prompt.py -- CreatePullRequestFromPrompt task.

Tests for pr_pipeline.py shared helpers are also included here.

All external calls (git, opencode, agents_md) are mocked.
Uses unittest + unittest.mock (not pytest, due to langsmith incompatibility).
"""

import unittest
from unittest.mock import MagicMock, patch

from src.create_pr_from_prompt import (
    CreatePullRequestFromPrompt,
    _build_full_prompt,
    _make_branch_name,
    _make_pr_title,
    _slugify,
)
from src.pr_pipeline import build_llm_env, build_prompt_pr_body


def _make_task(overrides=None):
    """Create a CreatePullRequestFromPrompt task with standard test inputs."""
    task = CreatePullRequestFromPrompt()
    task.input_properties = {
        "prompt": "Add a health check endpoint that returns 200 OK",
        "repoUrl": "https://github.com/org/repo.git",
        "repoBranch": "main",
        "branchPrefix": "agent",
        "githubToken": "ghp_test_token",
        "llmServer": {
            "provider": "anthropic",
            "apiKey": "sk-ant-test-key",
            "model": "claude-sonnet-4-20250514",
        },
        "opencodeTimeout": 60,
    }
    if overrides:
        task.input_properties.update(overrides)

    task._output_properties = {}
    task._comments = []
    task._status_lines = []

    def set_output(key, value):
        task._output_properties[key] = value

    def add_comment(msg):
        task._comments.append(msg)

    def set_status_line(msg):
        task._status_lines.append(msg)

    task.set_output_property = set_output
    task.add_comment = add_comment
    task.set_status_line = set_status_line
    return task


# Patch targets
P = "src.create_pr_from_prompt"
PP = "src.pr_pipeline"


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestValidation(unittest.TestCase):
    """Test input validation."""

    def test_missing_prompt(self):
        task = _make_task({"prompt": ""})
        with self.assertRaises(ValueError) as ctx:
            task.execute()
        self.assertIn("Prompt", str(ctx.exception))

    def test_missing_repo_url(self):
        task = _make_task({"repoUrl": ""})
        with self.assertRaises(ValueError) as ctx:
            task.execute()
        self.assertIn("Repository URL", str(ctx.exception))

    def test_missing_github_token(self):
        task = _make_task({"githubToken": ""})
        with self.assertRaises(ValueError) as ctx:
            task.execute()
        self.assertIn("GitHub token", str(ctx.exception))

    def test_missing_api_key(self):
        task = _make_task({"llmServer": {"provider": "anthropic", "apiKey": ""}})
        with self.assertRaises(ValueError) as ctx:
            task.execute()
        self.assertIn("API key", str(ctx.exception))

    def test_docker_model_runner_no_api_key_needed(self):
        """Docker Model Runner should not require an API key."""
        task = _make_task({"llmServer": {"provider": "docker-model-runner", "apiKey": ""}})
        with self.assertRaises(Exception) as ctx:
            task.execute()
        self.assertNotIn("API key", str(ctx.exception))


# ---------------------------------------------------------------------------
# Full pipeline tests
# ---------------------------------------------------------------------------


class TestFullPipeline(unittest.TestCase):
    """Test the happy-path pipeline: setup -> code -> deliver."""

    @patch(f"{PP}.create_pr", return_value="https://github.com/org/repo/pull/10")
    @patch(f"{PP}.push_branch")
    @patch(f"{PP}.stage_and_commit", return_value=True)
    @patch(f"{PP}.get_diff_stat", return_value="2 files changed, 30 insertions(+)")
    @patch(f"{PP}.cleanup_agents_md")
    @patch(f"{PP}.run_opencode")
    @patch(f"{PP}.inject_opencode_config", return_value="/workspace/opencode.json")
    @patch(f"{PP}.create_branch")
    @patch(f"{PP}.clone_repo")
    @patch(f"{PP}.configure_git")
    def test_happy_path(
        self,
        mock_configure_git,
        mock_clone,
        mock_create_branch,
        mock_inject_oc_config,
        mock_run_oc,
        mock_cleanup,
        mock_diff_stat,
        mock_stage_commit,
        mock_push,
        mock_create_pr,
    ):
        oc_result = MagicMock()
        oc_result.exit_code = 0
        oc_result.timed_out = False
        oc_result.needs_answer_bead_id = None
        mock_run_oc.return_value = oc_result

        task = _make_task()
        task.execute()

        # Verify outputs
        self.assertEqual(task._output_properties["prUrl"], "https://github.com/org/repo/pull/10")
        self.assertIn("agent/", task._output_properties["branchName"])

        # Verify git setup
        mock_configure_git.assert_called_once_with(
            "code-agent", "code-agent@release.digital.ai", "ghp_test_token"
        )
        mock_clone.assert_called_once_with("https://github.com/org/repo.git", "/workspace")
        mock_create_branch.assert_called_once()

        # Verify OpenCode invoked
        mock_run_oc.assert_called_once()
        call_kwargs = mock_run_oc.call_args[1]
        self.assertIn("health check", call_kwargs["prompt"])
        self.assertIn("Instructions", call_kwargs["prompt"])

        # Verify deliver
        mock_cleanup.assert_called_once_with("/workspace")
        mock_stage_commit.assert_called_once()
        mock_push.assert_called_once()
        mock_create_pr.assert_called_once()

    @patch(f"{PP}.cleanup_agents_md")
    @patch(f"{PP}.stage_and_commit", return_value=False)
    @patch(f"{PP}.run_opencode")
    @patch(f"{PP}.inject_opencode_config", return_value="/workspace/opencode.json")
    @patch(f"{PP}.create_branch")
    @patch(f"{PP}.clone_repo")
    @patch(f"{PP}.configure_git")
    def test_no_changes_produced(
        self,
        mock_configure_git,
        mock_clone,
        mock_create_branch,
        mock_inject_oc_config,
        mock_run_oc,
        mock_stage_commit,
        mock_cleanup,
    ):
        oc_result = MagicMock()
        oc_result.exit_code = 0
        oc_result.timed_out = False
        mock_run_oc.return_value = oc_result

        task = _make_task()
        task.execute()

        self.assertEqual(task._output_properties["prUrl"], "")
        self.assertIn("agent/", task._output_properties["branchName"])

    @patch(f"{PP}.run_opencode")
    @patch(f"{PP}.inject_opencode_config", return_value="/workspace/opencode.json")
    @patch(f"{PP}.create_branch")
    @patch(f"{PP}.clone_repo")
    @patch(f"{PP}.configure_git")
    def test_opencode_failure_raises(
        self,
        mock_configure_git,
        mock_clone,
        mock_create_branch,
        mock_inject_oc_config,
        mock_run_oc,
    ):
        oc_result = MagicMock()
        oc_result.exit_code = 1
        oc_result.timed_out = False
        mock_run_oc.return_value = oc_result

        task = _make_task()
        with self.assertRaises(RuntimeError) as ctx:
            task.execute()
        self.assertIn("exit code 1", str(ctx.exception))

    @patch(f"{PP}.create_pr", return_value="https://github.com/org/repo/pull/11")
    @patch(f"{PP}.push_branch")
    @patch(f"{PP}.stage_and_commit", return_value=True)
    @patch(f"{PP}.get_diff_stat", return_value="1 file changed")
    @patch(f"{PP}.cleanup_agents_md")
    @patch(f"{PP}.run_opencode")
    @patch(f"{PP}.inject_opencode_config", return_value="/workspace/opencode.json")
    @patch(f"{PP}.create_branch")
    @patch(f"{PP}.clone_repo")
    @patch(f"{PP}.configure_git")
    def test_opencode_timeout_continues(
        self,
        mock_configure_git,
        mock_clone,
        mock_create_branch,
        mock_inject_oc_config,
        mock_run_oc,
        mock_cleanup,
        mock_diff_stat,
        mock_stage_commit,
        mock_push,
        mock_create_pr,
    ):
        """Timeout is not fatal -- continues to deliver whatever was produced."""
        oc_result = MagicMock()
        oc_result.exit_code = 124
        oc_result.timed_out = True
        mock_run_oc.return_value = oc_result

        task = _make_task()
        task.execute()

        self.assertEqual(task._output_properties["prUrl"], "https://github.com/org/repo/pull/11")
        self.assertTrue(any("timed out" in c for c in task._comments))

    @patch(f"{PP}.create_pr", return_value="https://github.com/org/repo/pull/12")
    @patch(f"{PP}.push_branch")
    @patch(f"{PP}.stage_and_commit", return_value=True)
    @patch(f"{PP}.get_diff_stat", return_value="1 file changed")
    @patch(f"{PP}.cleanup_agents_md")
    @patch(f"{PP}.run_opencode")
    @patch(f"{PP}.inject_opencode_config", return_value="/workspace/opencode.json")
    @patch(f"{PP}.create_branch")
    @patch(f"{PP}.clone_repo")
    @patch(f"{PP}.configure_git")
    def test_custom_branch_prefix(
        self,
        mock_configure_git,
        mock_clone,
        mock_create_branch,
        mock_inject_oc_config,
        mock_run_oc,
        mock_cleanup,
        mock_diff_stat,
        mock_stage_commit,
        mock_push,
        mock_create_pr,
    ):
        oc_result = MagicMock()
        oc_result.exit_code = 0
        oc_result.timed_out = False
        mock_run_oc.return_value = oc_result

        task = _make_task({"branchPrefix": "feature"})
        task.execute()

        branch = task._output_properties["branchName"]
        self.assertTrue(branch.startswith("feature/"))


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestSlugify(unittest.TestCase):
    """Test the _slugify helper."""

    def test_basic(self):
        self.assertEqual(_slugify("Hello World"), "hello-world")

    def test_special_chars(self):
        self.assertEqual(_slugify("Add a health-check endpoint!"), "add-a-health-check-endpoint")

    def test_max_length(self):
        slug = _slugify("A" * 100)
        self.assertLessEqual(len(slug), 40)

    def test_empty(self):
        self.assertEqual(_slugify(""), "")

    def test_only_special_chars(self):
        self.assertEqual(_slugify("!@#$%"), "")

    def test_strips_trailing_hyphens(self):
        slug = _slugify("hello---world---")
        self.assertFalse(slug.endswith("-"))


class TestMakeBranchName(unittest.TestCase):
    """Test branch name generation."""

    def test_normal(self):
        name = _make_branch_name("agent", "Add health check")
        self.assertEqual(name, "agent/add-health-check")

    def test_empty_prompt_fallback(self):
        name = _make_branch_name("agent", "")
        self.assertEqual(name, "agent/changes")

    def test_special_chars_prompt(self):
        name = _make_branch_name("feature", "!!! urgent fix !!!")
        self.assertEqual(name, "feature/urgent-fix")


class TestMakePrTitle(unittest.TestCase):
    """Test PR title generation."""

    def test_short_prompt(self):
        title = _make_pr_title("Add health check endpoint")
        self.assertEqual(title, "Add health check endpoint")

    def test_multiline_prompt(self):
        title = _make_pr_title("Add health check\n\nDetailed description here")
        self.assertEqual(title, "Add health check")

    def test_truncation(self):
        long_title = "A" * 100
        title = _make_pr_title(long_title)
        self.assertLessEqual(len(title), 72)
        self.assertTrue(title.endswith("..."))


class TestBuildFullPrompt(unittest.TestCase):
    """Test prompt wrapping."""

    def test_includes_user_prompt(self):
        result = _build_full_prompt("Fix the login bug")
        self.assertIn("Fix the login bug", result)

    def test_includes_instructions(self):
        result = _build_full_prompt("Fix the login bug")
        self.assertIn("Instructions", result)
        self.assertIn("Do NOT commit", result)


class TestBuildPromptPrBody(unittest.TestCase):
    """Test PR body generation for prompt-driven tasks."""

    def test_contains_prompt(self):
        body = build_prompt_pr_body("Add logging to all API endpoints")
        self.assertIn("Add logging to all API endpoints", body)
        self.assertIn("Release Code Agent", body)

    def test_truncates_long_prompt(self):
        long_prompt = "x" * 3000
        body = build_prompt_pr_body(long_prompt)
        self.assertIn("truncated", body)
        # Body should contain at most 2000 chars of the prompt
        self.assertLess(body.index("truncated"), 2500)


if __name__ == "__main__":
    unittest.main()
