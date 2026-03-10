"""
llm_test_connection.py -- Test connection script for LLM server configuration.

Validates that the API key is valid by making a minimal API call
to the configured LLM provider.
"""

import json
import logging
import subprocess
from typing import Any, Dict, List

from digitalai.release.integration import BaseTask

logger = logging.getLogger(__name__)

# Provider-specific env var names for API keys
PROVIDER_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}

# Default models per provider (used when no model is specified)
_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4o-mini",
    "docker-model-runner": "ai/qwen3-coder",
}

# API endpoints per provider (for chat completion test)
_API_URLS = {
    "anthropic": "https://api.anthropic.com/v1/messages",
    "openai": "https://api.openai.com/v1/chat/completions",
}

# Docker Model Runner endpoint (models list -- fast, no inference needed)
_DOCKER_MODEL_RUNNER_URL = "http://model-runner.docker.internal/engines/v1/models"


def _auth_headers(provider: str, api_key: str) -> List[str]:
    """Build provider-specific auth headers for curl."""
    if provider == "anthropic":
        return [
            "-H", f"x-api-key: {api_key}",
            "-H", "anthropic-version: 2023-06-01",
            "-H", "content-type: application/json",
        ]
    return [
        "-H", f"Authorization: Bearer {api_key}",
        "-H", "Content-Type: application/json",
    ]


def _run_curl_test(url: str, headers: List[str], body: str, provider: str) -> None:
    """Run a curl request and raise on failure."""
    result = subprocess.run(
        ["curl", "-s", "-f", url] + headers + ["-d", body],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{provider.title()} API returned error: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )


def _test_docker_model_runner() -> None:
    """Test Docker Model Runner by listing available models (no inference needed)."""
    result = subprocess.run(
        ["curl", "-s", "-f", _DOCKER_MODEL_RUNNER_URL],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Docker Model Runner not reachable: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )


class LLMTestConnection(BaseTask):
    """
    Test connection script for code-agent.LLMServer configuration.

    Validates the LLM configuration by making a minimal API call
    using curl. This avoids needing the LLM SDK libraries installed
    just for connection testing.
    """

    def execute(self) -> None:
        server = self.input_properties.get("server", {})
        provider = server.get("provider", "anthropic")
        api_key = server.get("apiKey", "")
        model = server.get("model", "")

        if provider != "docker-model-runner" and not api_key:
            raise ValueError("API key is required")

        logger.info(f"Testing connection to {provider} provider...")

        try:
            if provider == "docker-model-runner":
                _test_docker_model_runner()
                logger.info("Docker Model Runner connection validated")
            elif provider in _API_URLS:
                test_model = model or _DEFAULT_MODELS[provider]
                body = json.dumps({
                    "model": test_model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "Hi"}],
                })
                _run_curl_test(
                    _API_URLS[provider],
                    _auth_headers(provider, api_key),
                    body,
                    provider,
                )
                logger.info(f"{provider.title()} API key validated (model: {test_model})")
            else:
                raise ValueError(f"Unknown provider: {provider}")

            self.set_output_property("commandResponse", {
                "status": "OK",
                "provider": provider,
                "model": model or _DEFAULT_MODELS.get(provider, "(default)"),
            })

        except Exception as e:
            raise RuntimeError(f"LLM connection test failed: {e}") from e
