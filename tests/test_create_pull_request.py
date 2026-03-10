"""
Tests for create_pull_request.py -- CreatePullRequest main pipeline task.

All external calls (beads, git, opencode, agents_md) are mocked.
Uses unittest + unittest.mock (not pytest, due to langsmith incompatibility).
"""

import unittest
from unittest.mock import MagicMock, call, patch

from src.create_pull_request import CreatePullRequest


def _make_task(overrides=None):
    """Create a CreatePullRequest task with standard test inputs."""
    task = CreatePullRequest()
    task.input_properties = {
        "beadsServer": {
            "host": "beads-server",
            "port": 3306,
            "projectId": "proj-1",
            "prefix": "bc",
            "syncMode": "direct",
            "actor": "test-bot",
        },
        "beadId": "bc-42",
        "repoUrl": "https://github.com/org/repo.git",
        "repoBranch": "main",
        "githubToken": "ghp_test_token",
        "llmServer": {
            "provider": "anthropic",
            "apiKey": "sk-ant-test-key",
            "model": "claude-sonnet-4-20250514",
        },
        "opencodeTimeout": 60,
        "questionTimeout": 10,
        "maxQuestionRounds": 3,
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


BEAD_DATA = {
    "id": "bc-42",
    "title": "Add user login",
    "description": "As a user, I want to log in so that I can access my account.",
    "status": "open",
    "design": "",
    "notes": "",
}


# Patch targets (module where names are looked up)
P = "src.create_pull_request"


class TestValidation(unittest.TestCase):
    """Test input validation."""

    def test_missing_bead_id(self):
        task = _make_task({"beadId": ""})
        with self.assertRaises(ValueError) as ctx:
            task.execute()
        self.assertIn("Bead ID", str(ctx.exception))

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

    def test_missing_project_id(self):
        task = _make_task({"beadsServer": {"projectId": ""}})
        with self.assertRaises(ValueError) as ctx:
            task.execute()
        self.assertIn("Project ID", str(ctx.exception))

    def test_missing_api_key(self):
        task = _make_task({"llmServer": {"provider": "anthropic", "apiKey": ""}})
        with self.assertRaises(ValueError) as ctx:
            task.execute()
        self.assertIn("API key", str(ctx.exception))

    def test_docker_model_runner_no_api_key_needed(self):
        """Docker Model Runner should not require an API key."""
        task = _make_task({"llmServer": {"provider": "docker-model-runner", "apiKey": ""}})
        # Should pass validation (will fail later at setup, but not at validation)
        with self.assertRaises(Exception) as ctx:
            task.execute()
        self.assertNotIn("API key", str(ctx.exception))


class TestFullPipeline(unittest.TestCase):
    """Test the happy-path pipeline: setup -> code -> deliver."""

    @patch(f"{P}.create_pr", return_value="https://github.com/org/repo/pull/1")
    @patch(f"{P}.push_branch")
    @patch(f"{P}.stage_and_commit", return_value=True)
    @patch(f"{P}.get_diff_stat", return_value="3 files changed, 50 insertions(+)")
    @patch(f"{P}.cleanup_agents_md")
    @patch(f"{P}.run_opencode")
    @patch(f"{P}.compose_prompt", return_value="test prompt")
    @patch(f"{P}.inject_agents_md", return_value="/workspace/AGENTS.md")
    @patch(f"{P}.create_branch")
    @patch(f"{P}.clone_repo")
    @patch(f"{P}.configure_git")
    @patch(f"{P}.BeadsClient")
    def test_happy_path(
        self,
        MockClient,
        mock_configure_git,
        mock_clone,
        mock_create_branch,
        mock_inject,
        mock_compose,
        mock_run_oc,
        mock_cleanup,
        mock_diff_stat,
        mock_stage_commit,
        mock_push,
        mock_create_pr,
    ):
        # Setup mock beads client
        client = MagicMock()
        client.show_bead.return_value = BEAD_DATA.copy()
        client.update_bead.return_value = True
        client.add_comment.return_value = True
        client.create_bead.return_value = {"id": "bc-99", "title": "Review: Add user login"}
        client.sync_push.return_value = True
        MockClient.from_server_properties.return_value = client

        # OpenCode returns successfully with no questions
        oc_result = MagicMock()
        oc_result.exit_code = 0
        oc_result.timed_out = False
        oc_result.needs_answer_bead_id = None
        mock_run_oc.return_value = oc_result

        task = _make_task()
        task.execute()

        # Verify outputs
        self.assertEqual(task._output_properties["prUrl"], "https://github.com/org/repo/pull/1")
        self.assertEqual(task._output_properties["branchName"], "beads/bc-42")
        self.assertEqual(task._output_properties["beadStatus"], "pr-created")

        # Verify setup calls
        mock_configure_git.assert_called_once_with(
            "test-bot", "test-bot@release.digital.ai", "ghp_test_token"
        )
        mock_clone.assert_called_once_with("https://github.com/org/repo.git", "/workspace")
        mock_create_branch.assert_called_once_with("/workspace", "beads/bc-42", "main")
        mock_inject.assert_called_once_with("/workspace", "bc-42")

        # Verify bead claimed
        client.update_bead.assert_any_call("bc-42", status="in_progress")

        # Verify code phase
        mock_compose.assert_called_once_with(BEAD_DATA)
        mock_run_oc.assert_called_once()

        # Verify deliver phase
        mock_cleanup.assert_called_once_with("/workspace")
        mock_stage_commit.assert_called_once_with(
            "/workspace", "feat: Add user login (bc-42)"
        )
        mock_push.assert_called_once_with("/workspace", "beads/bc-42")
        mock_create_pr.assert_called_once()

        # Verify review bead created
        client.create_bead.assert_called_once()

        # Verify final sync
        client.sync_push.assert_called()

    @patch(f"{P}.cleanup_agents_md")
    @patch(f"{P}.run_opencode")
    @patch(f"{P}.compose_prompt", return_value="test prompt")
    @patch(f"{P}.inject_agents_md", return_value="/workspace/AGENTS.md")
    @patch(f"{P}.create_branch")
    @patch(f"{P}.clone_repo")
    @patch(f"{P}.configure_git")
    @patch(f"{P}.BeadsClient")
    def test_no_changes_produced(
        self,
        MockClient,
        mock_configure_git,
        mock_clone,
        mock_create_branch,
        mock_inject,
        mock_compose,
        mock_run_oc,
        mock_cleanup,
    ):
        client = MagicMock()
        client.show_bead.return_value = BEAD_DATA.copy()
        MockClient.from_server_properties.return_value = client

        oc_result = MagicMock()
        oc_result.exit_code = 0
        oc_result.timed_out = False
        oc_result.needs_answer_bead_id = None
        mock_run_oc.return_value = oc_result

        # stage_and_commit returns False (no changes)
        with patch(f"{P}.stage_and_commit", return_value=False):
            task = _make_task()
            task.execute()

        self.assertEqual(task._output_properties["prUrl"], "")
        self.assertEqual(task._output_properties["beadStatus"], "no-changes")

    @patch(f"{P}.cleanup_agents_md")
    @patch(f"{P}.run_opencode")
    @patch(f"{P}.compose_prompt", return_value="test prompt")
    @patch(f"{P}.inject_agents_md", return_value="/workspace/AGENTS.md")
    @patch(f"{P}.create_branch")
    @patch(f"{P}.clone_repo")
    @patch(f"{P}.configure_git")
    @patch(f"{P}.BeadsClient")
    def test_bead_not_found(
        self,
        MockClient,
        mock_configure_git,
        mock_clone,
        mock_create_branch,
        mock_inject,
        mock_compose,
        mock_run_oc,
        mock_cleanup,
    ):
        client = MagicMock()
        client.show_bead.return_value = None
        MockClient.from_server_properties.return_value = client

        task = _make_task()
        with self.assertRaises(RuntimeError) as ctx:
            task.execute()
        self.assertIn("not found", str(ctx.exception))


class TestOpenCodeFailure(unittest.TestCase):
    """Test OpenCode error handling."""

    @patch(f"{P}.cleanup_agents_md")
    @patch(f"{P}.run_opencode")
    @patch(f"{P}.compose_prompt", return_value="test prompt")
    @patch(f"{P}.inject_agents_md", return_value="/workspace/AGENTS.md")
    @patch(f"{P}.create_branch")
    @patch(f"{P}.clone_repo")
    @patch(f"{P}.configure_git")
    @patch(f"{P}.BeadsClient")
    def test_opencode_failure_raises(
        self,
        MockClient,
        mock_configure_git,
        mock_clone,
        mock_create_branch,
        mock_inject,
        mock_compose,
        mock_run_oc,
        mock_cleanup,
    ):
        client = MagicMock()
        client.show_bead.return_value = BEAD_DATA.copy()
        MockClient.from_server_properties.return_value = client

        oc_result = MagicMock()
        oc_result.exit_code = 1
        oc_result.timed_out = False
        oc_result.needs_answer_bead_id = None
        mock_run_oc.return_value = oc_result

        task = _make_task()
        with self.assertRaises(RuntimeError) as ctx:
            task.execute()
        self.assertIn("exit code 1", str(ctx.exception))
        client.add_comment.assert_any_call("bc-42", "OpenCode failed with exit code 1")

    @patch(f"{P}.create_pr", return_value="https://github.com/org/repo/pull/2")
    @patch(f"{P}.push_branch")
    @patch(f"{P}.stage_and_commit", return_value=True)
    @patch(f"{P}.get_diff_stat", return_value="1 file changed")
    @patch(f"{P}.cleanup_agents_md")
    @patch(f"{P}.run_opencode")
    @patch(f"{P}.compose_prompt", return_value="test prompt")
    @patch(f"{P}.inject_agents_md", return_value="/workspace/AGENTS.md")
    @patch(f"{P}.create_branch")
    @patch(f"{P}.clone_repo")
    @patch(f"{P}.configure_git")
    @patch(f"{P}.BeadsClient")
    def test_opencode_timeout_continues(
        self,
        MockClient,
        mock_configure_git,
        mock_clone,
        mock_create_branch,
        mock_inject,
        mock_compose,
        mock_run_oc,
        mock_cleanup,
        mock_diff_stat,
        mock_stage_commit,
        mock_push,
        mock_create_pr,
    ):
        """Timeout is not fatal -- the pipeline continues to deliver whatever was produced."""
        client = MagicMock()
        client.show_bead.return_value = BEAD_DATA.copy()
        client.create_bead.return_value = {"id": "bc-100"}
        MockClient.from_server_properties.return_value = client

        oc_result = MagicMock()
        oc_result.exit_code = 124
        oc_result.timed_out = True
        oc_result.needs_answer_bead_id = None
        mock_run_oc.return_value = oc_result

        task = _make_task()
        task.execute()

        # Should still create PR
        self.assertEqual(task._output_properties["prUrl"], "https://github.com/org/repo/pull/2")
        client.add_comment.assert_any_call("bc-42", "OpenCode timed out after 60s")


class TestQuestionLoop(unittest.TestCase):
    """Test the question-answer loop (Phase 3)."""

    @patch(f"{P}.create_pr", return_value="https://github.com/org/repo/pull/3")
    @patch(f"{P}.push_branch")
    @patch(f"{P}.stage_and_commit", return_value=True)
    @patch(f"{P}.get_diff_stat", return_value="2 files changed")
    @patch(f"{P}.cleanup_agents_md")
    @patch(f"{P}.run_opencode")
    @patch(f"{P}.compose_prompt", return_value="test prompt")
    @patch(f"{P}.inject_agents_md", return_value="/workspace/AGENTS.md")
    @patch(f"{P}.create_branch")
    @patch(f"{P}.clone_repo")
    @patch(f"{P}.configure_git")
    @patch(f"{P}.BeadsClient")
    @patch(f"{P}.time")
    def test_one_question_answered(
        self,
        mock_time,
        MockClient,
        mock_configure_git,
        mock_clone,
        mock_create_branch,
        mock_inject,
        mock_compose,
        mock_run_oc,
        mock_cleanup,
        mock_diff_stat,
        mock_stage_commit,
        mock_push,
        mock_create_pr,
    ):
        # Make time.sleep a no-op for tests
        mock_time.sleep = MagicMock()

        client = MagicMock()
        client.show_bead.return_value = BEAD_DATA.copy()
        client.create_bead.return_value = {"id": "bc-101"}
        # list_comments returns an answer on first poll
        client.list_comments.return_value = [{"content": "Use OAuth2 for auth."}]
        MockClient.from_server_properties.return_value = client

        # First run: needs answer; second run: success
        oc_result_1 = MagicMock()
        oc_result_1.exit_code = 0
        oc_result_1.timed_out = False
        oc_result_1.needs_answer_bead_id = "bc-q1"

        oc_result_2 = MagicMock()
        oc_result_2.exit_code = 0
        oc_result_2.timed_out = False
        oc_result_2.needs_answer_bead_id = None

        mock_run_oc.side_effect = [oc_result_1, oc_result_2]

        task = _make_task()
        task.execute()

        # Verify two OpenCode invocations
        self.assertEqual(mock_run_oc.call_count, 2)

        # Second call should include the answer in the prompt
        second_call_prompt = mock_run_oc.call_args_list[1][1]["prompt"]
        self.assertIn("OAuth2", second_call_prompt)
        self.assertIn("bc-q1", second_call_prompt)

        # Verify PR created
        self.assertEqual(task._output_properties["prUrl"], "https://github.com/org/repo/pull/3")

    @patch(f"{P}.create_pr", return_value="https://github.com/org/repo/pull/4")
    @patch(f"{P}.push_branch")
    @patch(f"{P}.stage_and_commit", return_value=True)
    @patch(f"{P}.get_diff_stat", return_value="1 file changed")
    @patch(f"{P}.cleanup_agents_md")
    @patch(f"{P}.run_opencode")
    @patch(f"{P}.compose_prompt", return_value="test prompt")
    @patch(f"{P}.inject_agents_md", return_value="/workspace/AGENTS.md")
    @patch(f"{P}.create_branch")
    @patch(f"{P}.clone_repo")
    @patch(f"{P}.configure_git")
    @patch(f"{P}.BeadsClient")
    @patch(f"{P}.time")
    def test_question_timeout_proceeds(
        self,
        mock_time,
        MockClient,
        mock_configure_git,
        mock_clone,
        mock_create_branch,
        mock_inject,
        mock_compose,
        mock_run_oc,
        mock_cleanup,
        mock_diff_stat,
        mock_stage_commit,
        mock_push,
        mock_create_pr,
    ):
        mock_time.sleep = MagicMock()

        client = MagicMock()
        client.show_bead.side_effect = [
            BEAD_DATA.copy(),       # initial show_bead
            {"status": "open"},     # question bead check in poll loop
        ]
        client.create_bead.return_value = {"id": "bc-102"}
        # list_comments always returns empty (no answer)
        client.list_comments.return_value = []
        MockClient.from_server_properties.return_value = client

        # First run: needs answer; second run (after timeout): success
        oc_result_1 = MagicMock()
        oc_result_1.exit_code = 0
        oc_result_1.timed_out = False
        oc_result_1.needs_answer_bead_id = "bc-q2"

        oc_result_2 = MagicMock()
        oc_result_2.exit_code = 0
        oc_result_2.timed_out = False
        oc_result_2.needs_answer_bead_id = None

        mock_run_oc.side_effect = [oc_result_1, oc_result_2]

        task = _make_task()
        task.execute()

        # Second prompt should mention "best judgment"
        second_call_prompt = mock_run_oc.call_args_list[1][1]["prompt"]
        self.assertIn("best judgment", second_call_prompt)

        # Timeout comment added to question bead
        client.add_comment.assert_any_call(
            "bc-q2",
            "Question timed out after 10s. Agent proceeding with best judgment.",
        )

    @patch(f"{P}.cleanup_agents_md")
    @patch(f"{P}.run_opencode")
    @patch(f"{P}.compose_prompt", return_value="test prompt")
    @patch(f"{P}.inject_agents_md", return_value="/workspace/AGENTS.md")
    @patch(f"{P}.create_branch")
    @patch(f"{P}.clone_repo")
    @patch(f"{P}.configure_git")
    @patch(f"{P}.BeadsClient")
    @patch(f"{P}.time")
    def test_max_question_rounds_exceeded(
        self,
        mock_time,
        MockClient,
        mock_configure_git,
        mock_clone,
        mock_create_branch,
        mock_inject,
        mock_compose,
        mock_run_oc,
        mock_cleanup,
    ):
        mock_time.sleep = MagicMock()

        client = MagicMock()
        client.show_bead.return_value = BEAD_DATA.copy()
        client.list_comments.return_value = [{"content": "answer"}]
        MockClient.from_server_properties.return_value = client

        # Every run returns a question -- should stop after maxQuestionRounds
        oc_result_with_question = MagicMock()
        oc_result_with_question.exit_code = 0
        oc_result_with_question.timed_out = False
        oc_result_with_question.needs_answer_bead_id = "bc-qN"

        # 4 runs: initial + 3 resumes (max rounds = 3), all with questions
        mock_run_oc.side_effect = [oc_result_with_question] * 4

        # After breaking out of question loop, it will check exit_code for fatal failure.
        # exit_code=0 + needs_answer_bead_id set -> not fatal, so it proceeds to deliver.
        with patch(f"{P}.stage_and_commit", return_value=False):
            task = _make_task()
            task.execute()

        # 4 OpenCode calls: 1 initial + 3 resumed
        self.assertEqual(mock_run_oc.call_count, 4)

        # Comment about max rounds
        client.add_comment.assert_any_call(
            "bc-42",
            "Max question rounds (3) exceeded. Proceeding with best judgment.",
        )


class TestLLMEnv(unittest.TestCase):
    """Test LLM environment variable construction."""

    def test_anthropic_env(self):
        task = _make_task()
        env = task._build_llm_env({"provider": "anthropic", "apiKey": "sk-ant-key"})
        self.assertEqual(env, {"ANTHROPIC_API_KEY": "sk-ant-key"})

    def test_openai_env(self):
        task = _make_task()
        env = task._build_llm_env({"provider": "openai", "apiKey": "sk-openai-key"})
        self.assertEqual(env, {"OPENAI_API_KEY": "sk-openai-key"})

    def test_unknown_provider_defaults_anthropic(self):
        task = _make_task()
        env = task._build_llm_env({"provider": "custom", "apiKey": "key123"})
        self.assertEqual(env, {"ANTHROPIC_API_KEY": "key123"})

    def test_docker_model_runner_env(self):
        task = _make_task()
        env = task._build_llm_env({"provider": "docker-model-runner"})
        self.assertEqual(env, {})


class TestPRBody(unittest.TestCase):
    """Test PR body construction."""

    def test_pr_body_contains_bead_id(self):
        task = _make_task()
        body = task._build_pr_body("bc-42", "Add login feature", "2 files changed")
        self.assertIn("bc-42", body)
        self.assertIn("Add login feature", body)
        self.assertIn("2 files changed", body)
        self.assertIn("Release Code Agent", body)


class TestQuestionBeadClosed(unittest.TestCase):
    """Test that a closed question bead with notes is treated as an answer."""

    @patch(f"{P}.create_pr", return_value="https://github.com/org/repo/pull/5")
    @patch(f"{P}.push_branch")
    @patch(f"{P}.stage_and_commit", return_value=True)
    @patch(f"{P}.get_diff_stat", return_value="1 file changed")
    @patch(f"{P}.cleanup_agents_md")
    @patch(f"{P}.run_opencode")
    @patch(f"{P}.compose_prompt", return_value="test prompt")
    @patch(f"{P}.inject_agents_md", return_value="/workspace/AGENTS.md")
    @patch(f"{P}.create_branch")
    @patch(f"{P}.clone_repo")
    @patch(f"{P}.configure_git")
    @patch(f"{P}.BeadsClient")
    @patch(f"{P}.time")
    def test_closed_question_bead_with_notes(
        self,
        mock_time,
        MockClient,
        mock_configure_git,
        mock_clone,
        mock_create_branch,
        mock_inject,
        mock_compose,
        mock_run_oc,
        mock_cleanup,
        mock_diff_stat,
        mock_stage_commit,
        mock_push,
        mock_create_pr,
    ):
        mock_time.sleep = MagicMock()

        client = MagicMock()
        # First call: main bead lookup; second call: question bead lookup (closed with notes)
        client.show_bead.side_effect = [
            BEAD_DATA.copy(),
            {"status": "closed", "notes": "Use JWT tokens for auth."},
        ]
        client.list_comments.return_value = []  # No comments, but bead closed with notes
        client.create_bead.return_value = {"id": "bc-103"}
        MockClient.from_server_properties.return_value = client

        oc_result_1 = MagicMock()
        oc_result_1.exit_code = 0
        oc_result_1.timed_out = False
        oc_result_1.needs_answer_bead_id = "bc-q3"

        oc_result_2 = MagicMock()
        oc_result_2.exit_code = 0
        oc_result_2.timed_out = False
        oc_result_2.needs_answer_bead_id = None

        mock_run_oc.side_effect = [oc_result_1, oc_result_2]

        task = _make_task()
        task.execute()

        # Second prompt should include the notes from the closed bead
        second_call_prompt = mock_run_oc.call_args_list[1][1]["prompt"]
        self.assertIn("JWT tokens", second_call_prompt)


if __name__ == "__main__":
    unittest.main()
