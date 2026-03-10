"""
Tests for opencode_runner.py -- OpenCode headless invocation.

All subprocess calls and file I/O are mocked; no real opencode binary is needed.
"""

import os
import unittest
from unittest.mock import MagicMock, mock_open, patch

from src.opencode_runner import (
    NEEDS_ANSWER_FILE,
    OpenCodeResult,
    _check_needs_answer,
    _invoke,
    compose_prompt,
    run_opencode,
)

# Patch target prefixes
P = "src.opencode_runner"


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
    """Test run_opencode integration — patches _invoke to isolate subprocess layer."""

    @patch(f"{P}._check_needs_answer")
    @patch("os.remove")
    @patch(f"{P}._invoke")
    def test_successful_run(self, mock_invoke, mock_remove, mock_needs):
        mock_invoke.return_value = (0, "Code generated successfully.", False)
        mock_needs.return_value = None

        result = run_opencode("Implement feature", "/workspace")

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Code generated", result.output)
        self.assertFalse(result.timed_out)
        self.assertIsNone(result.needs_answer_bead_id)

        # Verify _invoke received the correct command
        cmd = mock_invoke.call_args[0][0]
        self.assertEqual(cmd[0], "opencode")
        self.assertIn("run", cmd)
        self.assertIn("--dir", cmd)
        self.assertIn("/workspace", cmd)
        self.assertIn("--print-logs", cmd)

    @patch(f"{P}._check_needs_answer")
    @patch("os.remove")
    @patch(f"{P}._invoke")
    def test_run_with_model(self, mock_invoke, mock_remove, mock_needs):
        mock_invoke.return_value = (0, "ok", False)
        mock_needs.return_value = None

        run_opencode("prompt", "/workspace", model="claude-sonnet-4-20250514")

        cmd = mock_invoke.call_args[0][0]
        self.assertIn("-m", cmd)
        self.assertIn("claude-sonnet-4-20250514", cmd)

    @patch(f"{P}._check_needs_answer")
    @patch("os.remove")
    @patch(f"{P}._invoke")
    def test_timeout(self, mock_invoke, mock_remove, mock_needs):
        mock_invoke.return_value = (1, "", True)
        mock_needs.return_value = None

        result = run_opencode("prompt", "/workspace", timeout=1800)

        self.assertTrue(result.timed_out)

    @patch(f"{P}._check_needs_answer")
    @patch("os.remove")
    @patch(f"{P}._invoke")
    def test_needs_answer_detected(self, mock_invoke, mock_remove, mock_needs):
        mock_invoke.return_value = (0, "I have a question", False)
        mock_needs.return_value = "bc-99"

        result = run_opencode("prompt", "/workspace")

        self.assertEqual(result.needs_answer_bead_id, "bc-99")

    @patch(f"{P}._check_needs_answer")
    @patch("os.remove")
    @patch(f"{P}._invoke")
    def test_env_variables_set(self, mock_invoke, mock_remove, mock_needs):
        mock_invoke.return_value = (0, "", False)
        mock_needs.return_value = None

        run_opencode(
            "prompt", "/workspace",
            llm_env={"ANTHROPIC_API_KEY": "sk-test-123"}
        )

        # env is the third positional arg to _invoke(cmd, cwd, env, timeout)
        env = mock_invoke.call_args[0][2]
        self.assertEqual(env["OPENCODE_DISABLE_AUTOUPDATE"], "1")
        self.assertEqual(env["OPENCODE_DISABLE_LSP_DOWNLOAD"], "1")
        self.assertEqual(env["OPENCODE_DISABLE_PRUNE"], "1")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-test-123")

    @patch(f"{P}._check_needs_answer")
    @patch("os.remove", side_effect=FileNotFoundError)
    @patch(f"{P}._invoke")
    def test_clears_needs_answer_file_before_run(self, mock_invoke, mock_remove, mock_needs):
        """Should attempt to remove the signal file before running, even if not present."""
        mock_invoke.return_value = (0, "", False)
        mock_needs.return_value = None

        # Should not raise even if file doesn't exist
        run_opencode("prompt", "/workspace")
        mock_remove.assert_called_once_with(NEEDS_ANSWER_FILE)

    @patch(f"{P}._check_needs_answer")
    @patch("os.remove")
    @patch(f"{P}._invoke")
    def test_nonzero_exit_code(self, mock_invoke, mock_remove, mock_needs):
        mock_invoke.return_value = (1, "Error occurred\nfatal error", False)
        mock_needs.return_value = None

        result = run_opencode("prompt", "/workspace")

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Error occurred", result.output)
        self.assertIn("fatal error", result.output)
        self.assertFalse(result.timed_out)


class TestInvoke(unittest.TestCase):
    """Test _invoke subprocess+selector layer directly."""

    def _make_mock_popen(self, stdout_text="", returncode=0):
        """Create a mock Popen with a pipe-like stdout."""
        proc = MagicMock()
        # Build a list of lines to serve via readline(); final "" signals EOF
        lines = stdout_text.splitlines(keepends=True)
        lines.append("")  # EOF sentinel
        proc.stdout = MagicMock()
        proc.stdout.readline = MagicMock(side_effect=lines)
        proc.returncode = returncode
        proc.kill = MagicMock()
        proc.wait = MagicMock()
        return proc

    def _make_mock_selector(self, proc, num_events):
        """Build a mock DefaultSelector that yields *num_events* events then stops.

        Each call to select() returns the proc.stdout ready for reading.
        After *num_events* calls, get_map() returns an empty dict to signal
        that stdout has been unregistered (EOF).
        """
        mock_sel_instance = MagicMock()

        # Track how many times select() has been called
        call_count = {"n": 0}

        def fake_select(timeout=None):
            call_count["n"] += 1
            if call_count["n"] <= num_events:
                key = MagicMock()
                key.fileobj = proc.stdout
                return [(key, None)]
            return []

        mock_sel_instance.select = MagicMock(side_effect=fake_select)

        # get_map() returns non-empty while events remain, empty after
        def fake_get_map():
            if call_count["n"] <= num_events:
                return {"something": True}
            return {}

        mock_sel_instance.get_map = MagicMock(side_effect=fake_get_map)
        mock_sel_instance.register = MagicMock()
        mock_sel_instance.unregister = MagicMock()
        mock_sel_instance.close = MagicMock()

        return mock_sel_instance

    @patch("selectors.DefaultSelector")
    @patch("subprocess.Popen")
    def test_successful_invoke(self, mock_popen_cls, mock_sel_cls):
        """Normal run: two lines of output, exit code 0."""
        proc = self._make_mock_popen("Line 1\nLine 2\n", returncode=0)
        mock_popen_cls.return_value = proc

        # Two lines then EOF readline returns ""
        sel = self._make_mock_selector(proc, num_events=3)
        mock_sel_cls.return_value = sel

        exit_code, output, timed_out = _invoke(["opencode", "run"], "/ws", {}, 60)

        self.assertEqual(exit_code, 0)
        self.assertIn("Line 1", output)
        self.assertIn("Line 2", output)
        self.assertFalse(timed_out)
        mock_popen_cls.assert_called_once()

    @patch("selectors.DefaultSelector")
    @patch("subprocess.Popen")
    def test_nonzero_exit(self, mock_popen_cls, mock_sel_cls):
        """Non-zero exit code is returned."""
        proc = self._make_mock_popen("error output\n", returncode=2)
        mock_popen_cls.return_value = proc

        sel = self._make_mock_selector(proc, num_events=2)
        mock_sel_cls.return_value = sel

        exit_code, output, timed_out = _invoke(["opencode", "run"], "/ws", {}, 60)

        self.assertEqual(exit_code, 2)
        self.assertIn("error output", output)
        self.assertFalse(timed_out)

    @patch("selectors.DefaultSelector")
    @patch("subprocess.Popen")
    def test_empty_output(self, mock_popen_cls, mock_sel_cls):
        """Process produces no output."""
        proc = self._make_mock_popen("", returncode=0)
        mock_popen_cls.return_value = proc

        # EOF immediately — one select call returns the EOF readline
        sel = self._make_mock_selector(proc, num_events=1)
        mock_sel_cls.return_value = sel

        exit_code, output, timed_out = _invoke(["opencode", "run"], "/ws", {}, 60)

        self.assertEqual(exit_code, 0)
        self.assertEqual(output, "")
        self.assertFalse(timed_out)

    @patch("time.monotonic")
    @patch("selectors.DefaultSelector")
    @patch("subprocess.Popen")
    def test_timeout_kills_process(self, mock_popen_cls, mock_sel_cls, mock_time):
        """When deadline is exceeded, process is killed and timed_out=True."""
        proc = self._make_mock_popen("", returncode=1)
        proc.returncode = None  # process didn't exit naturally
        mock_popen_cls.return_value = proc

        # Simulate time: first call sets deadline, second call is past it
        mock_time.side_effect = [100.0, 200.0]  # deadline=100+5=105, next check=200>105

        sel = MagicMock()
        sel.get_map.return_value = {"something": True}
        mock_sel_cls.return_value = sel

        exit_code, output, timed_out = _invoke(["opencode", "run"], "/ws", {}, 5)

        self.assertTrue(timed_out)
        proc.kill.assert_called_once()

    @patch("subprocess.Popen")
    def test_popen_start_failure(self, mock_popen_cls):
        """If Popen itself raises, return error gracefully."""
        mock_popen_cls.side_effect = OSError("command not found")

        exit_code, output, timed_out = _invoke(["opencode", "run"], "/ws", {}, 60)

        self.assertEqual(exit_code, 1)
        self.assertIn("command not found", output)
        self.assertFalse(timed_out)

    @patch("selectors.DefaultSelector")
    @patch("subprocess.Popen")
    def test_output_streamed_via_print(self, mock_popen_cls, mock_sel_cls):
        """Verify that output lines are printed (streamed) in real-time."""
        proc = self._make_mock_popen("streaming line\n", returncode=0)
        mock_popen_cls.return_value = proc

        sel = self._make_mock_selector(proc, num_events=2)
        mock_sel_cls.return_value = sel

        with patch("builtins.print") as mock_print:
            _invoke(["opencode", "run"], "/ws", {}, 60)

        # Check that the streaming line was printed with end="" and flush=True
        printed_calls = [
            c for c in mock_print.call_args_list
            if c[0] and "streaming line" in str(c[0][0])
        ]
        self.assertTrue(len(printed_calls) > 0, "Output line should be printed in real-time")


if __name__ == "__main__":
    unittest.main()
