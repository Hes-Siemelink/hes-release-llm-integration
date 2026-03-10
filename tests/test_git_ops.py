"""
Tests for git_ops.py -- Git and GitHub CLI operations.

All subprocess calls are mocked; no real git/gh binary is needed.
"""

import os
import subprocess
import unittest
from unittest.mock import MagicMock, call, patch

from src.git_ops import (
    clone_repo,
    configure_git,
    create_branch,
    create_pr,
    get_diff_stat,
    push_branch,
    stage_and_commit,
)


def _ok(stdout="", stderr=""):
    """Create a successful CompletedProcess."""
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


def _fail(code=1, stdout="", stderr="error"):
    """Create a failed CompletedProcess."""
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr=stderr)


class TestConfigureGit(unittest.TestCase):
    """Test configure_git sets identity and auth."""

    @patch("subprocess.run")
    def test_configure_git_sets_identity(self, mock_run):
        mock_run.return_value = _ok()
        configure_git("bot", "bot@example.com", "ghp_token123")

        # Should call: git config user.name, git config user.email,
        # git config url, gh auth status = 4 calls
        self.assertEqual(mock_run.call_count, 4)

        # Check user.name
        first_call_cmd = mock_run.call_args_list[0][0][0]
        self.assertIn("user.name", first_call_cmd)
        self.assertIn("bot", first_call_cmd)

        # Check user.email
        second_call_cmd = mock_run.call_args_list[1][0][0]
        self.assertIn("user.email", second_call_cmd)
        self.assertIn("bot@example.com", second_call_cmd)

        # Check URL rewrite includes token
        third_call_cmd = mock_run.call_args_list[2][0][0]
        self.assertIn("url.https://ghp_token123@github.com/.insteadOf", third_call_cmd)

    @patch("subprocess.run")
    def test_configure_git_gh_auth_warning(self, mock_run):
        """gh auth status failure should not raise (it's a warning)."""
        def side_effect(cmd, **kwargs):
            if "gh" in cmd:
                return _fail(stderr="not authenticated")
            return _ok()

        mock_run.side_effect = side_effect
        # Should not raise
        configure_git("bot", "bot@example.com", "ghp_token123")


class TestCloneRepo(unittest.TestCase):
    """Test clone_repo function."""

    @patch("subprocess.run")
    @patch("os.path.isdir")
    def test_clone_repo_fresh(self, mock_isdir, mock_run):
        mock_isdir.return_value = False
        mock_run.return_value = _ok()

        clone_repo("https://github.com/org/repo.git", "/workspace")

        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd, ["git", "clone", "https://github.com/org/repo.git", "/workspace"])

    @patch("subprocess.run")
    @patch("os.path.isdir")
    def test_clone_repo_already_exists(self, mock_isdir, mock_run):
        mock_isdir.return_value = True

        clone_repo("https://github.com/org/repo.git", "/workspace")

        # Should not call git clone
        mock_run.assert_not_called()


class TestCreateBranch(unittest.TestCase):
    """Test create_branch function."""

    @patch("subprocess.run")
    def test_create_branch(self, mock_run):
        mock_run.return_value = _ok()

        create_branch("/workspace", "feature/bc-42", "main")

        cmd = mock_run.call_args[0][0]
        self.assertEqual(
            cmd,
            ["git", "checkout", "-b", "feature/bc-42", "origin/main"]
        )
        self.assertEqual(mock_run.call_args[1]["cwd"], "/workspace")

    @patch("subprocess.run")
    def test_create_branch_custom_base(self, mock_run):
        mock_run.return_value = _ok()

        create_branch("/workspace", "fix/thing", "develop")

        cmd = mock_run.call_args[0][0]
        self.assertIn("origin/develop", cmd)


class TestStageAndCommit(unittest.TestCase):
    """Test stage_and_commit function."""

    @patch("subprocess.run")
    def test_commit_with_changes(self, mock_run):
        def side_effect(cmd, **kwargs):
            if cmd[:3] == ["git", "diff", "--stat"] and "HEAD" in cmd:
                return _ok(stdout=" file.py | 5 +++++\n 1 file changed")
            if "ls-files" in cmd:
                return _ok(stdout="")
            if cmd[:3] == ["git", "diff", "--cached"]:
                return _fail(code=1)  # non-zero means there ARE staged changes
            return _ok()

        mock_run.side_effect = side_effect
        result = stage_and_commit("/workspace", "Implement feature")
        self.assertTrue(result)

    @patch("subprocess.run")
    def test_no_changes(self, mock_run):
        def side_effect(cmd, **kwargs):
            if cmd[:3] == ["git", "diff", "--stat"] and "HEAD" in cmd:
                return _ok(stdout="")
            if "ls-files" in cmd:
                return _ok(stdout="")
            return _ok()

        mock_run.side_effect = side_effect
        result = stage_and_commit("/workspace", "Nothing")
        self.assertFalse(result)

    @patch("subprocess.run")
    def test_only_orchestrator_artifacts(self, mock_run):
        """If all changes are in AGENTS.md/.beads, commit should be skipped."""
        call_count = [0]

        def side_effect(cmd, **kwargs):
            if cmd[:3] == ["git", "diff", "--stat"] and "HEAD" in cmd:
                return _ok(stdout=" AGENTS.md | 3 +++\n 1 file changed")
            if "ls-files" in cmd:
                return _ok(stdout="")
            if cmd[:3] == ["git", "diff", "--cached"]:
                return _ok()  # zero means nothing staged after exclusion
            return _ok()

        mock_run.side_effect = side_effect
        result = stage_and_commit("/workspace", "Orchestrator only")
        self.assertFalse(result)


class TestPushBranch(unittest.TestCase):
    """Test push_branch function."""

    @patch("subprocess.run")
    def test_push_branch(self, mock_run):
        mock_run.return_value = _ok()

        push_branch("/workspace", "feature/bc-42")

        cmd = mock_run.call_args[0][0]
        self.assertEqual(
            cmd, ["git", "push", "-u", "origin", "feature/bc-42"]
        )

    @patch("subprocess.run")
    def test_push_branch_failure(self, mock_run):
        mock_run.return_value = _fail(stderr="rejected")
        with self.assertRaises(subprocess.CalledProcessError):
            push_branch("/workspace", "feature/bc-42")


class TestCreatePR(unittest.TestCase):
    """Test create_pr function."""

    @patch("subprocess.run")
    def test_create_pr_returns_url(self, mock_run):
        mock_run.return_value = _ok(stdout="https://github.com/org/repo/pull/123\n")

        url = create_pr(
            workspace_dir="/workspace",
            title="Implement bc-42",
            body="Resolves bead bc-42",
            base_branch="main",
            head_branch="feature/bc-42",
            github_token="ghp_token123",
        )

        self.assertEqual(url, "https://github.com/org/repo/pull/123")

        cmd = mock_run.call_args[0][0]
        self.assertIn("gh", cmd)
        self.assertIn("pr", cmd)
        self.assertIn("create", cmd)
        self.assertIn("--title", cmd)

        # Token should be in env, not in command
        env = mock_run.call_args[1]["env"]
        self.assertEqual(env["GITHUB_TOKEN"], "ghp_token123")

    @patch("subprocess.run")
    def test_create_pr_failure(self, mock_run):
        mock_run.return_value = _fail(stderr="not a git repo")
        with self.assertRaises(subprocess.CalledProcessError):
            create_pr("/workspace", "Title", "Body", "main", "branch", "token")


class TestGetDiffStat(unittest.TestCase):
    """Test get_diff_stat function."""

    @patch("subprocess.run")
    def test_get_diff_stat(self, mock_run):
        mock_run.return_value = _ok(stdout=" src/main.py | 10 +++++++\n 1 file changed")

        result = get_diff_stat("/workspace")
        self.assertIn("src/main.py", result)

    @patch("subprocess.run")
    def test_get_diff_stat_failure(self, mock_run):
        mock_run.return_value = _fail()

        result = get_diff_stat("/workspace")
        self.assertEqual(result, "See commits for details.")


if __name__ == "__main__":
    unittest.main()
