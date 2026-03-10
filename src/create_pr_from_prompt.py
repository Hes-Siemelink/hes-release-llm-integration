"""
create_pr_from_prompt.py -- Simple prompt-driven PR creation task.

A simplified version of CreatePullRequest that takes a text prompt
instead of a bead ID. No beads server, no question loop -- just:
  Phase 1 (Setup):   Validate inputs, configure git, clone, branch, inject config
  Phase 2 (Code):    Run OpenCode with the user's prompt
  Phase 3 (Deliver): Cleanup, commit, push, create PR
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from digitalai.release.integration import BaseTask

from src.opencode_runner import OpenCodeResult
from src.pr_pipeline import (
    DEFAULT_WORKSPACE,
    build_prompt_pr_body,
    deliver_pr,
    invoke_opencode,
    setup_opencode,
    setup_workspace,
)


@dataclass
class PromptPipelineContext:
    """State threaded through the prompt-driven pipeline phases."""
    # Inputs
    prompt: str
    repo_url: str
    repo_branch: str
    branch_prefix: str
    github_token: str
    llm_server: Dict[str, Any]
    opencode_timeout: int
    workspace: str

    # Set during setup
    branch_name: str = ""
    model: Optional[str] = None
    llm_env: Dict[str, str] = None  # type: ignore[assignment]
    opencode_config: Optional[str] = None


class CreatePullRequestFromPrompt(BaseTask):
    """
    Release container task: implement changes from a text prompt and create a PR.

    Input properties (from type-definitions.yaml):
        prompt          -- Text description of the changes to implement
        repoUrl         -- GitHub repository URL to clone
        repoBranch      -- Base branch (default: main)
        branchPrefix    -- Prefix for the feature branch (default: agent)
        githubToken     -- GitHub PAT with repo+PR permissions
        llmServer       -- LLMServer CI config (provider, apiKey, model)
        opencodeTimeout -- Max seconds for OpenCode to run (default: 1800)

    Output properties:
        prUrl       -- URL of the created pull request
        branchName  -- Name of the feature branch
    """

    def execute(self) -> None:
        ctx = self._extract_inputs()
        self._validate_inputs(ctx)
        self._phase_setup(ctx)
        oc_result = self._phase_code(ctx)
        self._check_fatal_failure(oc_result)
        self._phase_deliver(ctx)

    # -------------------------------------------------------------------
    # Input extraction and validation
    # -------------------------------------------------------------------

    def _extract_inputs(self) -> PromptPipelineContext:
        """Extract and normalize input properties into a PromptPipelineContext."""
        props = self.input_properties
        return PromptPipelineContext(
            prompt=props.get("prompt", ""),
            repo_url=props.get("repoUrl", ""),
            repo_branch=props.get("repoBranch", "main"),
            branch_prefix=props.get("branchPrefix", "agent"),
            github_token=props.get("githubToken", ""),
            llm_server=props.get("llmServer", {}),
            opencode_timeout=int(props.get("opencodeTimeout", 1800)),
            workspace=DEFAULT_WORKSPACE,
        )

    def _validate_inputs(self, ctx: PromptPipelineContext) -> None:
        """Validate required input properties."""
        if not ctx.prompt:
            raise ValueError("Prompt is required")
        if not ctx.repo_url:
            raise ValueError("Repository URL is required")
        if not ctx.github_token:
            raise ValueError("GitHub token is required")
        provider = ctx.llm_server.get("provider", "anthropic")
        if provider != "docker-model-runner" and not ctx.llm_server.get("apiKey"):
            raise ValueError("LLM API key is required")

    # -------------------------------------------------------------------
    # Phase 1: Setup
    # -------------------------------------------------------------------

    def _phase_setup(self, ctx: PromptPipelineContext) -> None:
        """Configure git, clone repo, create branch, inject OpenCode config."""
        self._set_phase("setup")

        ctx.branch_name = _make_branch_name(ctx.branch_prefix, ctx.prompt)
        setup_workspace(
            ctx.repo_url, ctx.workspace, ctx.branch_name,
            ctx.repo_branch, "code-agent", ctx.github_token,
        )
        ctx.opencode_config, ctx.model, ctx.llm_env = setup_opencode(ctx.workspace, ctx.llm_server)

        self._set_phase("setup-complete")
        self._comment(f"Workspace ready. Branch: {ctx.branch_name}")

    # -------------------------------------------------------------------
    # Phase 2: Code
    # -------------------------------------------------------------------

    def _phase_code(self, ctx: PromptPipelineContext) -> OpenCodeResult:
        """Run OpenCode with the user's prompt."""
        self._set_phase("code")

        full_prompt = _build_full_prompt(ctx.prompt)
        oc_result = invoke_opencode(
            prompt=full_prompt,
            workspace_dir=ctx.workspace,
            model=ctx.model,
            timeout=ctx.opencode_timeout,
            opencode_config=ctx.opencode_config,
            llm_env=ctx.llm_env,
        )

        if oc_result.timed_out:
            self._comment(f"OpenCode timed out after {ctx.opencode_timeout}s")

        return oc_result

    def _check_fatal_failure(self, oc_result: OpenCodeResult) -> None:
        """Raise if OpenCode exited with a non-recoverable error."""
        if oc_result.exit_code != 0 and not oc_result.timed_out:
            raise RuntimeError(f"OpenCode failed with exit code {oc_result.exit_code}")

    # -------------------------------------------------------------------
    # Phase 3: Deliver
    # -------------------------------------------------------------------

    def _phase_deliver(self, ctx: PromptPipelineContext) -> None:
        """Cleanup, commit, push, create PR."""
        self._set_phase("deliver")

        pr_body = build_prompt_pr_body(ctx.prompt)
        pr_title = _make_pr_title(ctx.prompt)
        commit_msg = f"feat: {pr_title}"

        pr_url = deliver_pr(
            workspace_dir=ctx.workspace,
            branch_name=ctx.branch_name,
            base_branch=ctx.repo_branch,
            github_token=ctx.github_token,
            pr_title=pr_title,
            pr_body=pr_body,
            commit_message=commit_msg,
        )

        if not pr_url:
            self._comment("Agent completed but produced no code changes.")
            self.set_output_property("prUrl", "")
            self.set_output_property("branchName", ctx.branch_name)
            return

        self._set_phase("complete")
        self.set_output_property("prUrl", pr_url)
        self.set_output_property("branchName", ctx.branch_name)
        self._comment(f"Done. PR: {pr_url}")

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def _set_phase(self, phase: str) -> None:
        """Update the task status line in Release UI."""
        print(f"Phase: {phase}")
        try:
            self.set_status_line(f"Phase: {phase}")
        except Exception:
            pass

    def _comment(self, message: str) -> None:
        """Add a comment to the Release task activity log."""
        print(message)
        try:
            self.add_comment(message)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _slugify(text: str, max_len: int = 40) -> str:
    """Convert free text to a git-safe branch slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:max_len].rstrip("-")


def _make_branch_name(prefix: str, prompt: str) -> str:
    """Create a feature branch name from the prefix and prompt text."""
    slug = _slugify(prompt)
    if not slug:
        slug = "changes"
    return f"{prefix}/{slug}"


def _make_pr_title(prompt: str, max_len: int = 72) -> str:
    """Create a PR title from the first line of the prompt."""
    first_line = prompt.split("\n", 1)[0].strip()
    if len(first_line) <= max_len:
        return first_line
    return first_line[: max_len - 3] + "..."


def _build_full_prompt(prompt: str) -> str:
    """Wrap the user's prompt with standard instructions."""
    return (
        f"{prompt}\n\n"
        f"## Instructions\n\n"
        f"1. Read the AGENTS.md file in this workspace if present for project-specific guidance.\n"
        f"2. Implement the changes described above.\n"
        f"3. Run any available tests to verify your work.\n"
        f"4. Do NOT commit or push -- the orchestrator handles that.\n"
        f"5. When done, simply exit."
    )
