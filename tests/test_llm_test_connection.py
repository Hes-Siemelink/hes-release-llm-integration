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

        self.assertEqual(task._output_properties["commandResponse"]["success"], "true")
        self.assertIn("anthropic", task._output_properties["commandResponse"]["output"])

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

        self.assertIn(
            "claude-opus-4-20250514",
            task._output_properties["commandResponse"]["output"],
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

        self.assertEqual(task._output_properties["commandResponse"]["success"], "true")
        self.assertIn("openai", task._output_properties["commandResponse"]["output"])

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


class TestLLMTestConnectionDockerModelRunner(unittest.TestCase):
    """Test Docker Model Runner connection testing."""

    @patch("subprocess.run")
    def test_docker_model_runner_success(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"data":[{"id":"ai/qwen3-coder"}]}', stderr=""
        )
        task = _make_task({"provider": "docker-model-runner"})
        task.execute()

        resp = task._output_properties["commandResponse"]
        self.assertEqual(resp["success"], "true")
        self.assertIn("docker-model-runner", resp["output"])
        self.assertIn("ai/qwen3-coder", resp["output"])

        # Verify curl hits the models endpoint (not chat completion)
        cmd = mock_run.call_args[0][0]
        self.assertIn("http://model-runner.docker.internal/engines/v1/models", cmd)

    @patch("subprocess.run")
    def test_docker_model_runner_no_api_key_needed(self, mock_run):
        """Docker Model Runner should not require an API key."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="{}", stderr=""
        )
        task = _make_task({"provider": "docker-model-runner", "apiKey": ""})
        task.execute()  # Should not raise ValueError

        self.assertEqual(task._output_properties["commandResponse"]["success"], "true")

    @patch("subprocess.run")
    def test_docker_model_runner_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=7, stdout="",
            stderr="curl: (7) Failed to connect"
        )
        task = _make_task({"provider": "docker-model-runner"})
        with self.assertRaises(RuntimeError) as ctx:
            task.execute()
        self.assertIn("LLM connection test failed", str(ctx.exception))

    @patch("subprocess.run")
    def test_docker_model_runner_with_custom_model(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="{}", stderr=""
        )
        task = _make_task({
            "provider": "docker-model-runner",
            "model": "ai/llama3.2",
        })
        task.execute()

        self.assertIn(
            "ai/llama3.2",
            task._output_properties["commandResponse"]["output"],
        )

    @patch("subprocess.run")
    def test_docker_model_runner_with_custom_url(self, mock_run):
        """Custom URL is used for the models endpoint."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"data":[{"id":"ai/qwen3-coder"}]}', stderr=""
        )
        task = _make_task({
            "provider": "docker-model-runner",
            "url": "http://custom-host:8080",
        })
        task.execute()

        cmd = mock_run.call_args[0][0]
        self.assertIn("http://custom-host:8080/engines/v1/models", cmd)
        self.assertNotIn("model-runner.docker.internal", " ".join(cmd))

    @patch("subprocess.run")
    def test_docker_model_runner_empty_url_uses_default(self, mock_run):
        """Empty URL falls back to the default Docker Model Runner endpoint."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"data":[{"id":"ai/qwen3-coder"}]}', stderr=""
        )
        task = _make_task({
            "provider": "docker-model-runner",
            "url": "",
        })
        task.execute()

        cmd = mock_run.call_args[0][0]
        self.assertIn("http://model-runner.docker.internal/engines/v1/models", cmd)


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

    def test_default_model_shown(self):
        """When no model specified, output shows the provider's default model."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="{}", stderr=""
            )
            task = _make_task({"provider": "anthropic", "apiKey": "key"})
            task.execute()
            self.assertIn(
                "claude-sonnet-4-20250514",
                task._output_properties["commandResponse"]["output"],
            )


if __name__ == "__main__":
    unittest.main()
