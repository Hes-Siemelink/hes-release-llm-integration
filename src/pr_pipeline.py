"""
pr_pipeline.py -- Shared pull-request pipeline logic.

Extracts the common orchestration steps used by both CreatePullRequest
(bead-driven) and CreatePullRequestFromPrompt (prompt-driven) tasks:
  - LLM environment construction
  - Git identity / clone / branch
  - OpenCode config injection
  - OpenCode invocation
  - Cleanup, commit, push, PR creation
  - Release UI helpers (_set_phase, _comment)
"""

from typing import Any, Dict, Optional

from src.agents_md import cleanup_agents_md, cleanup_opencode_config, inject_opencode_config
from src.git_ops import (
    clone_repo,
    configure_git,
    create_branch,
    create_pr,
    get_diff_stat,
    push_branch,
    stage_and_commit,
)
from src.opencode_runner import DEFAULT_OPENCODE_CONFIG, OpenCodeResult, run_opencode

# Default workspace directory inside the container
DEFAULT_WORKSPACE = "/workspace"


# ---------------------------------------------------------------------------
# LLM environment
# ---------------------------------------------------------------------------


def build_llm_env(llm_server: Dict[str, Any]) -> Dict[str, str]:
    """Build environment variables for the LLM provider.

    Maps provider names to the API-key env var that OpenCode expects.
    Docker Model Runner needs no API key.
    """
    env: Dict[str, str] = {}
    provider = llm_server.get("provider", "anthropic")
    api_key = llm_server.get("apiKey", "")

    if provider == "docker-model-runner":
        pass  # local model runner -- no API key env var needed
    elif provider == "anthropic":
        env["ANTHROPIC_API_KEY"] = api_key
    elif provider == "openai":
        env["OPENAI_API_KEY"] = api_key
    else:
        env["ANTHROPIC_API_KEY"] = api_key  # default to anthropic-style

    return env


# Default models per provider (used when no model is specified)
_DEFAULT_MODELS: Dict[str, str] = {
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
    "docker-model-runner": "ai/qwen3-coder",
}


def normalize_model(provider: str, model: Optional[str]) -> Optional[str]:
    """Normalize a model identifier to the provider_id/model_id format.

    OpenCode's ``-m`` flag requires the fully-qualified format
    ``provider_id/model_id``.  Users may configure just the model name
    (e.g., ``ai/qwen3-coder``) or the bare name (``qwen3-coder``).
    This function:

    1. Falls back to the provider default when *model* is empty.
    2. Returns the model as-is when it already starts with ``provider/``.
    3. Prepends ``provider/`` otherwise.

    For docker-model-runner the model keys include an ``ai/`` namespace
    (e.g., ``ai/qwen3-coder``).  A bare name like ``qwen3-coder`` is
    expanded to ``docker-model-runner/ai/qwen3-coder``.
    """
    if not model:
        default = _DEFAULT_MODELS.get(provider)
        if default:
            model = default
            print(f"No model specified, using default for {provider}: {model}")
        else:
            return None

    # Already fully qualified (starts with provider/)
    if model.startswith(f"{provider}/"):
        return model

    # Docker Model Runner models are keyed as ai/<name>.  If the user
    # provided just the bare model name (e.g. "qwen3-coder"), prepend "ai/".
    if provider == "docker-model-runner" and "/" not in model:
        model = f"ai/{model}"

    qualified = f"{provider}/{model}"
    print(f"Normalized model: {model} -> {qualified}")
    return qualified


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------


def setup_workspace(
    repo_url: str,
    workspace_dir: str,
    branch_name: str,
    base_branch: str,
    actor: str,
    github_token: str,
) -> None:
    """Configure git identity, clone the repo, and create a feature branch."""
    configure_git(actor, f"{actor}@release.digital.ai", github_token)
    clone_repo(repo_url, workspace_dir)
    create_branch(workspace_dir, branch_name, base_branch)


def setup_opencode(
    workspace_dir: str,
    llm_server: Dict[str, Any],
) -> tuple:
    """Inject opencode config and build LLM env.

    Returns:
        (opencode_config_path, model_or_none, llm_env_dict)
    """
    opencode_config = inject_opencode_config(workspace_dir, llm_server=llm_server)
    llm_env = build_llm_env(llm_server)
    provider = llm_server.get("provider", "anthropic")
    raw_model = llm_server.get("model") or None
    model = normalize_model(provider, raw_model)
    return opencode_config, model, llm_env


# ---------------------------------------------------------------------------
# Code phase
# ---------------------------------------------------------------------------


def invoke_opencode(
    prompt: str,
    workspace_dir: str,
    model: Optional[str],
    timeout: int,
    opencode_config: Optional[str],
    llm_env: Dict[str, str],
) -> OpenCodeResult:
    """Run OpenCode with the given prompt and return the result."""
    return run_opencode(
        prompt=prompt,
        workspace_dir=workspace_dir,
        model=model,
        timeout=timeout,
        opencode_config=opencode_config or DEFAULT_OPENCODE_CONFIG,
        llm_env=llm_env,
    )


# ---------------------------------------------------------------------------
# Deliver phase
# ---------------------------------------------------------------------------


def deliver_pr(
    workspace_dir: str,
    branch_name: str,
    base_branch: str,
    github_token: str,
    pr_title: str,
    pr_body: str,
    commit_message: str,
) -> Optional[str]:
    """Cleanup artifacts, commit, push, create PR.

    Returns the PR URL, or None if no changes were produced.
    """
    cleanup_agents_md(workspace_dir)
    cleanup_opencode_config(workspace_dir)

    has_changes = stage_and_commit(workspace_dir, commit_message)
    if not has_changes:
        return None

    push_branch(workspace_dir, branch_name)

    diff_stat = get_diff_stat(workspace_dir)
    full_body = f"{pr_body}\n\n## Changes\n\n{diff_stat}"

    pr_url = create_pr(
        workspace_dir=workspace_dir,
        title=pr_title,
        body=full_body,
        base_branch=base_branch,
        head_branch=branch_name,
        github_token=github_token,
    )
    return pr_url


# ---------------------------------------------------------------------------
# PR body builders
# ---------------------------------------------------------------------------


def build_prompt_pr_body(prompt: str) -> str:
    """Build a PR body for a prompt-driven task."""
    # Truncate very long prompts in the PR body
    display_prompt = prompt if len(prompt) <= 2000 else prompt[:2000] + "\n\n_(truncated)_"
    return (
        f"## Summary\n\n"
        f"Automated implementation from a text prompt.\n\n"
        f"## Prompt\n\n"
        f"{display_prompt}\n\n"
        f"---\n\n"
        f"*This PR was created automatically by the Release Code Agent plugin. "
        f"Review the changes and provide feedback on this PR.*"
    )
