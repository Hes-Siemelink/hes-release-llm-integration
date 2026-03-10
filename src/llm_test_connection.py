"""
llm_test_connection.py -- Test connection script for LLM server configuration.

Validates that the API key is valid by making a minimal API call
to the configured LLM provider.

Raises:
    ValueError: If API key is not provided.
    RuntimeError: If LLM connection test fails.
"""

import json
import logging
import subprocess
from typing import Any, Dict

from digitalai.release.integration import BaseTask

logger = logging.getLogger(__name__)

# Provider-specific env var names for API keys
PROVIDER_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


class LLMTestConnection(BaseTask):
    """Test connection script for code-agent.LLMServer configuration.

    Validates the LLM configuration by making a minimal API call
    using curl. This avoids needing the LLM SDK libraries installed
    just for connection testing.

    Raises:
        ValueError: If API key is not provided.
        RuntimeError: If LLM connection test fails.
    """

    def execute(self) -> None:
        """Execute the LLM connection test.

        This method validates the LLM configuration by making a minimal API call
        using curl. It handles both Anthropic and OpenAI providers.

        Args:
            self: The LLMTestConnection instance.

        Raises:
            ValueError: If API key is not provided.
            RuntimeError: If LLM connection test fails.
        """
        server = self.input_properties.get("server", {})
        provider = server.get("provider", "anthropic")
        api_key = server.get("apiKey", "")
        model = server.get("model", "")

        if not api_key:
            raise ValueError("API key is required")

        logger.info(f"Testing connection to {provider} provider...")

        try:
            if provider == "anthropic":
                self._test_anthropic(api_key, model)
            elif provider == "openai":
                self._test_openai(api_key, model)
            else:
                raise ValueError(f"Unknown provider: {provider}")

            self.set_output_property("commandResponse", {
                "status": "OK",
                "provider": provider,
                "model": model or "(default)",
            })

        except Exception as e:
            raise RuntimeError(f"LLM connection test failed: {e}") from e

    def _test_anthropic(self, api_key: str, model: str) -> None:
        """Test Anthropic API by sending a minimal messages request.

        Args:
            api_key: The Anthropic API key.
            model: The model to test with.

        Raises:
            RuntimeError: If the Anthropic API returns an error.
        """
        test_model = model or "claude-sonnet-4-20250514"
        result = subprocess.run(
            [
                "curl", "-s", "-f",
                "https://api.anthropic.com/v1/messages",
                "-H", f"x-api-key: {api_key}",
                "-H", "anthropic-version: 2023-06-01",
                "-H", "content-type: application/json",
                "-d", json.dumps({
                    "model": test_model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "Hi"}],
                }),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Anthropic API returned error: {result.stderr.strip() or result.stdout.strip()}"
            )
        logger.info(f"Anthropic API key validated (model: {test_model})")

    def _test_openai(self, api_key: str, model: str) -> None:
        """Test OpenAI API by sending a minimal chat completion request.

        Args:
            api_key: The OpenAI API key.
            model: The model to test with.

        Raises:
            RuntimeError: If the OpenAI API returns an error.
        """
        test_model = model or "gpt-4o-mini"
        result = subprocess.run(
            [
                "curl", "-s", "-f",
                "https://api.openai.com/v1/chat/completions",
                "-H", f"Authorization: Bearer {api_key}",
                "-H", "Content-Type: application/json",
                "-d", json.dumps({
                    "model": test_model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "Hi"}],
                }),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"OpenAI API returned error: {result.stderr.strip() or result.stdout.strip()}"
            )
        logger.info(f"OpenAI API key validated (model: {test_model})")
