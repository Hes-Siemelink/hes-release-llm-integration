"""
Tests for llm_test_connection.py -- LLM Server test connection script.

All subprocess calls are mocked; no real API calls are made.
"""

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from src.llm_test_connection import LLMTestConnection


def _make_task(server_props):
    """Create a LLMTestConnection task with given server properties."""
    task = LLMTestConnection()
    task.input_properties = {"server": server_props}
    task._output_properties = {}

    def set_output(key, value):
        task._output_properties[key] = value

    task.set_output_property = set_output
    return task


class TestLLMTestConnectionAnthropic(unittest.TestCase):
    """Test Anthropic connection testing."""

    @patch("subprocess.run")
    def test_anthropic_success(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"id":"msg_123","content":[{"text":"Hi"}]}', stderr=""
        )
        task = _make_task({"provider": "anthropic", "apiKey": "sk-test-key"})
        task.execute()

        self.assertEqual(task._output_properties["commandResponse"]["status"], "OK")
        self.assertEqual(task._output_properties["commandResponse"]["provider"], "anthropic")

        # Verify curl was called with Anthropic API
        cmd = mock_run.call_args[0][0]
        self.assertIn("https://api.anthropic.com/v1/messages", cmd)
        self.assertIn("x-api-key: sk-test-key", cmd)

    @patch("subprocess.run")
    def test_anthropic_with_custom_model(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="{}", stderr=""
        )
        task = _make_task({
            "provider": "anthropic",
            "apiKey": "sk-key",
            "model": "claude-opus-4-20250514",
        })
        task.execute()

        self.assertEqual(
            task._output_properties["commandResponse"]["model"],
            "claude-opus-4-20250514"
        )

    @patch("subprocess.run")
    def test_anthropic_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=22,
            stdout='{"error":{"message":"Invalid API key"}}',
            stderr="curl: (22) HTTP 401"
        )
        task = _make_task({"provider": "anthropic", "apiKey": "bad-key"})
        with self.assertRaises(RuntimeError) as ctx:
            task.execute()
        self.assertIn("LLM connection test failed", str(ctx.exception))


class TestLLMTestConnectionOpenAI(unittest.TestCase):
    """Test OpenAI connection testing."""

    @patch("subprocess.run")
    def test_openai_success(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"choices":[{"message":{"content":"Hi"}}]}', stderr=""
        )
        task = _make_task({"provider": "openai", "apiKey": "sk-openai-key"})
        task.execute()

        self.assertEqual(task._output_properties["commandResponse"]["status"], "OK")
        self.assertEqual(task._output_properties["commandResponse"]["provider"], "openai")

        cmd = mock_run.call_args[0][0]
        self.assertIn("https://api.openai.com/v1/chat/completions", cmd)
        self.assertIn("Authorization: Bearer sk-openai-key", cmd)

    @patch("subprocess.run")
    def test_openai_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=22, stdout="", stderr="401 Unauthorized"
        )
        task = _make_task({"provider": "openai", "apiKey": "bad-key"})
        with self.assertRaises(RuntimeError):
            task.execute()


class TestLLMTestConnectionValidation(unittest.TestCase):
    """Test input validation."""

    def test_missing_api_key(self):
        task = _make_task({"provider": "anthropic", "apiKey": ""})
        with self.assertRaises(ValueError) as ctx:
            task.execute()
        self.assertIn("API key is required", str(ctx.exception))

    def test_unknown_provider(self):
        task = _make_task({"provider": "unknown", "apiKey": "key"})
        with self.assertRaises(RuntimeError):
            task.execute()

    def test_default_model_label(self):
        """When no model specified, output shows '(default)'."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="{}", stderr=""
            )
            task = _make_task({"provider": "anthropic", "apiKey": "key"})
            task.execute()
            self.assertEqual(
                task._output_properties["commandResponse"]["model"],
                "(default)"
            )


if __name__ == "__main__":
    unittest.main()
