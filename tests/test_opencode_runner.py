"""
Tests for opencode_runner.py -- OpenCode headless invocation.

All subprocess calls and file I/O are mocked; no real opencode binary is needed.
"""

import os
import subprocess
import unittest
from unittest.mock import MagicMock, mock_open, patch

from src.opencode_runner import (
    NEEDS_ANSWER_FILE,
    OpenCodeResult,
    _check_needs_answer,
    compose_prompt,
    run_opencode,
)


class TestComposePrompt(unittest.TestCase):
    """Test compose_prompt function."""

    def test_basic_prompt(self):
        bead = {
            "id": "bc-42",
            "title": "Add login page",
            "description": "As a user, I want a login page so that I can authenticate.",
        }
        prompt = compose_prompt(bead)

        self.assertIn("bc-42", prompt)
        self.assertIn("Add login page", prompt)
        self.assertIn("As a user", prompt)
        self.assertIn("AGENTS.md", prompt)
        self.assertIn("Do NOT commit or push", prompt)

    def test_prompt_with_design_and_notes(self):
        bead = {
            "id": "bc-43",
            "title": "Refactor DB layer",
            "description": "Refactor the database layer.",
            "design": "Use repository pattern.",
            "notes": "Check existing test coverage first.",
        }
        prompt = compose_prompt(bead)

        self.assertIn("Design Notes", prompt)
        self.assertIn("repository pattern", prompt)
        self.assertIn("Additional Notes", prompt)
        self.assertIn("test coverage", prompt)

    def test_prompt_without_optional_fields(self):
        bead = {
            "id": "bc-44",
            "title": "Simple fix",
            "description": "Fix the typo.",
        }
        prompt = compose_prompt(bead)

        self.assertNotIn("Design Notes", prompt)
        self.assertNotIn("Additional Notes", prompt)

    def test_prompt_with_empty_optional_fields(self):
        bead = {
            "id": "bc-45",
            "title": "Task",
            "description": "Do the thing.",
            "design": "",
            "notes": "",
        }
        prompt = compose_prompt(bead)

        self.assertNotIn("Design Notes", prompt)
        self.assertNotIn("Additional Notes", prompt)

    def test_prompt_with_none_optional_fields(self):
        bead = {
            "id": "bc-46",
            "title": "Task",
            "description": "Do it.",
            "design": None,
            "notes": None,
        }
        prompt = compose_prompt(bead)

        self.assertNotIn("Design Notes", prompt)
        self.assertNotIn("Additional Notes", prompt)

    def test_prompt_missing_fields(self):
        """Handles missing fields gracefully (defaults)."""
        prompt = compose_prompt({})
        self.assertIn("unknown", prompt)
        self.assertIn("Untitled", prompt)


class TestCheckNeedsAnswer(unittest.TestCase):
    """Test _check_needs_answer helper."""

    @patch("builtins.open", mock_open(read_data="bc-99\n"))
    def test_reads_bead_id_from_file(self):
        result = _check_needs_answer()
        self.assertEqual(result, "bc-99")

    @patch("builtins.open", mock_open(read_data=""))
    def test_empty_file_returns_none(self):
        result = _check_needs_answer()
        self.assertIsNone(result)

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_missing_file_returns_none(self, _):
        result = _check_needs_answer()
        self.assertIsNone(result)


class TestRunOpencode(unittest.TestCase):
    """Test run_opencode function."""

    @patch("src.opencode_runner._check_needs_answer")
    @patch("os.remove")
    @patch("subprocess.run")
    def test_successful_run(self, mock_run, mock_remove, mock_needs):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="Code generated successfully.", stderr=""
        )
        mock_needs.return_value = None

        result = run_opencode("Implement feature", "/workspace")

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Code generated", result.output)
        self.assertFalse(result.timed_out)
        self.assertIsNone(result.needs_answer_bead_id)

        # Verify opencode was called with correct args
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "opencode")
        self.assertIn("run", cmd)
        self.assertIn("--dir", cmd)
        self.assertIn("/workspace", cmd)
        self.assertIn("--print-logs", cmd)

    @patch("src.opencode_runner._check_needs_answer")
    @patch("os.remove")
    @patch("subprocess.run")
    def test_run_with_model(self, mock_run, mock_remove, mock_needs):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr=""
        )
        mock_needs.return_value = None

        run_opencode("prompt", "/workspace", model="claude-sonnet-4-20250514")

        cmd = mock_run.call_args[0][0]
        self.assertIn("-m", cmd)
        self.assertIn("claude-sonnet-4-20250514", cmd)

    @patch("src.opencode_runner._check_needs_answer")
    @patch("os.remove")
    @patch("subprocess.run")
    def test_timeout(self, mock_run, mock_remove, mock_needs):
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="opencode", timeout=1800
        )
        mock_needs.return_value = None

        result = run_opencode("prompt", "/workspace", timeout=1800)

        self.assertEqual(result.exit_code, 124)
        self.assertTrue(result.timed_out)

    @patch("src.opencode_runner._check_needs_answer")
    @patch("os.remove")
    @patch("subprocess.run")
    def test_needs_answer_detected(self, mock_run, mock_remove, mock_needs):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="I have a question", stderr=""
        )
        mock_needs.return_value = "bc-99"

        result = run_opencode("prompt", "/workspace")

        self.assertEqual(result.needs_answer_bead_id, "bc-99")

    @patch("src.opencode_runner._check_needs_answer")
    @patch("os.remove")
    @patch("subprocess.run")
    def test_env_variables_set(self, mock_run, mock_remove, mock_needs):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        mock_needs.return_value = None

        run_opencode(
            "prompt", "/workspace",
            llm_env={"ANTHROPIC_API_KEY": "sk-test-123"}
        )

        env = mock_run.call_args[1]["env"]
        self.assertEqual(env["OPENCODE_DISABLE_AUTOUPDATE"], "1")
        self.assertEqual(env["OPENCODE_DISABLE_LSP_DOWNLOAD"], "1")
        self.assertEqual(env["OPENCODE_DISABLE_PRUNE"], "1")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-test-123")

    @patch("src.opencode_runner._check_needs_answer")
    @patch("os.remove", side_effect=FileNotFoundError)
    @patch("subprocess.run")
    def test_clears_needs_answer_file_before_run(self, mock_run, mock_remove, mock_needs):
        """Should attempt to remove the signal file before running, even if not present."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        mock_needs.return_value = None

        # Should not raise even if file doesn't exist
        run_opencode("prompt", "/workspace")
        mock_remove.assert_called_once_with(NEEDS_ANSWER_FILE)

    @patch("src.opencode_runner._check_needs_answer")
    @patch("os.remove")
    @patch("subprocess.run")
    def test_nonzero_exit_code(self, mock_run, mock_remove, mock_needs):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout="Error occurred", stderr="fatal error"
        )
        mock_needs.return_value = None

        result = run_opencode("prompt", "/workspace")

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Error occurred", result.output)
        self.assertIn("fatal error", result.output)
        self.assertFalse(result.timed_out)


if __name__ == "__main__":
    unittest.main()
