"""
create_pull_request.py -- Main pipeline task: implement a bead and create a PR.

Orchestrates the 4-phase pipeline:
  Phase 1 (Setup):   Validate inputs, init beads, configure git, clone, branch, inject AGENTS.md
  Phase 2 (Code):    Compose prompt from bead data, run OpenCode headlessly
  Phase 3 (Q&A):     Detect question beads, poll for answers, resume agent
  Phase 4 (Deliver): Cleanup artifacts, commit, push, create PR, update bead

Ports the orchestration logic from beads-coder's entrypoint.sh, run-agent.sh,
and deliver.sh into a single Release container task.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from digitalai.release.integration import BaseTask

from src.agents_md import cleanup_agents_md, inject_agents_md
from src.beads_client import BeadsClient
from src.git_ops import (
    clone_repo,
    configure_git,
    create_branch,
    create_pr,
    get_diff_stat,
    push_branch,
    stage_and_commit,
)
from src.opencode_runner import OpenCodeResult, compose_prompt, run_opencode

logger = logging.getLogger(__name__)

# Default workspace directory inside the container
DEFAULT_WORKSPACE = "/workspace"


@dataclass
class PipelineContext:
    """Shared state threaded through pipeline phases.

    Fields ``client`` and ``bead_data`` are initialised during the setup
    phase and are guaranteed to be non-None for all subsequent phases.
    They default to sentinel values here only to allow construction before
    setup runs.
    """
    # Inputs
    bead_id: str
    repo_url: str
    repo_branch: str
    github_token: str
    beads_server: Dict[str, Any]
    llm_server: Dict[str, Any]
    opencode_timeout: int
    question_timeout: int
    max_question_rounds: int
    workspace: str

    # Set during _phase_setup -- always non-None after setup
    client: "BeadsClient" = None  # type: ignore[assignment]
    bead_data: Dict[str, Any] = None  # type: ignore[assignment]
    branch_name: str = ""
    model: Optional[str] = None
    llm_env: Dict[str, str] = None  # type: ignore[assignment]


class CreatePullRequest(BaseTask):
    """
    Release container task: implement a bead story and create a pull request.

    Input properties (from type-definitions.yaml):
        beadsServer      -- BeadsServer CI config (host, port, projectId, prefix, syncMode, actor)
        beadId           -- The bead ID to implement
        repoUrl          -- GitHub repository URL to clone
        repoBranch       -- Base branch (default: main)
        githubToken      -- GitHub PAT with repo+PR permissions
        llmServer        -- LLMServer CI config (provider, apiKey, model)
        opencodeTimeout  -- Max seconds for OpenCode to run (default: 1800)
        questionTimeout  -- Max seconds to wait for question answers (default: 3600)
        maxQuestionRounds -- Max question-answer round trips (default: 5)

    Output properties:
        prUrl       -- URL of the created pull request
        branchName  -- Name of the feature branch
        beadStatus  -- Final status of the bead
    """

    def execute(self) -> None:
        ctx = self._extract_inputs()
        self._validate_inputs(ctx)
        self._phase_setup(ctx)
        oc_result = self._phase_code(ctx)
        oc_result = self._phase_question_loop(ctx, oc_result)
        self._check_fatal_failure(ctx, oc_result)
        self._phase_deliver(ctx)

    # -------------------------------------------------------------------
    # Input extraction and validation
    # -------------------------------------------------------------------

    def _extract_inputs(self) -> PipelineContext:
        """Extract and normalize input properties into a PipelineContext."""
        props = self.input_properties
        return PipelineContext(
            bead_id=props.get("beadId", ""),
            repo_url=props.get("repoUrl", ""),
            repo_branch=props.get("repoBranch", "main"),
            github_token=props.get("githubToken", ""),
            beads_server=props.get("beadsServer", {}),
            llm_server=props.get("llmServer", {}),
            opencode_timeout=int(props.get("opencodeTimeout", 1800)),
            question_timeout=int(props.get("questionTimeout", 3600)),
            max_question_rounds=int(props.get("maxQuestionRounds", 5)),
            workspace=DEFAULT_WORKSPACE,
        )

    def _validate_inputs(self, ctx: PipelineContext) -> None:
        """Validate required input properties."""
        if not ctx.bead_id:
            raise ValueError("Bead ID is required")
        if not ctx.repo_url:
            raise ValueError("Repository URL is required")
        if not ctx.github_token:
            raise ValueError("GitHub token is required")
        if not ctx.beads_server.get("projectId"):
            raise ValueError("Beads Server Project ID is required")
        provider = ctx.llm_server.get("provider", "anthropic")
        if provider != "docker-model-runner" and not ctx.llm_server.get("apiKey"):
            raise ValueError("LLM API key is required")

    # -------------------------------------------------------------------
    # Phase 1: Setup
    # -------------------------------------------------------------------

    def _phase_setup(self, ctx: PipelineContext) -> None:
        """Initialize beads, clone repo, create branch, inject AGENTS.md."""
        self._set_phase("setup")

        ctx.client = BeadsClient.from_server_properties(ctx.beads_server)
        ctx.client.init_metadata()
        self._comment(f"Starting work on bead {ctx.bead_id}")

        bead_data = ctx.client.show_bead(ctx.bead_id)
        if bead_data is None:
            raise RuntimeError(f"Bead {ctx.bead_id} not found")
        ctx.bead_data = bead_data

        actor = ctx.beads_server.get("actor", "beads-coder")
        configure_git(actor, f"{actor}@release.digital.ai", ctx.github_token)

        clone_repo(ctx.repo_url, ctx.workspace)
        ctx.branch_name = f"beads/{ctx.bead_id}"
        create_branch(ctx.workspace, ctx.branch_name, ctx.repo_branch)

        ctx.client.update_bead(ctx.bead_id, status="in_progress")
        ctx.client.add_comment(ctx.bead_id, f"Claimed by Release task. Branch: {ctx.branch_name}")

        inject_agents_md(ctx.workspace, ctx.bead_id)

        ctx.llm_env = self._build_llm_env(ctx.llm_server)
        ctx.model = ctx.llm_server.get("model") or None

        self._set_phase("setup-complete")

    # -------------------------------------------------------------------
    # Phase 2: Code
    # -------------------------------------------------------------------

    def _phase_code(self, ctx: PipelineContext) -> OpenCodeResult:
        """Compose prompt and invoke OpenCode."""
        self._set_phase("code")

        prompt = compose_prompt(ctx.bead_data)
        oc_result = run_opencode(
            prompt=prompt,
            workspace_dir=ctx.workspace,
            model=ctx.model,
            timeout=ctx.opencode_timeout,
            llm_env=ctx.llm_env,
        )

        if oc_result.timed_out:
            ctx.client.add_comment(ctx.bead_id, f"OpenCode timed out after {ctx.opencode_timeout}s")

        return oc_result

    # -------------------------------------------------------------------
    # Phase 3: Question loop
    # -------------------------------------------------------------------

    def _phase_question_loop(self, ctx: PipelineContext, oc_result: OpenCodeResult) -> OpenCodeResult:
        """Handle question-answer rounds until no more questions or limit reached."""
        question_round = 0

        while oc_result.needs_answer_bead_id:
            question_round += 1

            if question_round > ctx.max_question_rounds:
                ctx.client.add_comment(
                    ctx.bead_id,
                    f"Max question rounds ({ctx.max_question_rounds}) exceeded. Proceeding with best judgment.",
                )
                break

            self._set_phase(f"question-loop-{question_round}")
            question_bead_id = oc_result.needs_answer_bead_id
            logger.info(f"Question detected: {question_bead_id} (round {question_round})")

            ctx.client.sync_push()

            answer = self._poll_for_answer(ctx.client, question_bead_id, ctx.question_timeout)
            resume_prompt = self._build_resume_prompt(ctx, question_bead_id, answer)

            self._set_phase(f"code-resumed-{question_round}")

            oc_result = run_opencode(
                prompt=resume_prompt,
                workspace_dir=ctx.workspace,
                model=ctx.model,
                timeout=ctx.opencode_timeout,
                llm_env=ctx.llm_env,
            )

        ctx.client.add_comment(ctx.bead_id, f"Coding phase complete ({question_round} question round(s)).")
        return oc_result

    def _build_resume_prompt(self, ctx: PipelineContext, question_bead_id: str, answer: Optional[str]) -> str:
        """Build the prompt to resume coding after a question is answered (or timed out)."""
        if answer:
            return (
                f"The answer to your question (bead {question_bead_id}) is:\n\n"
                f"{answer}\n\n"
                f"Please continue implementing bead {ctx.bead_id} based on this answer."
            )

        ctx.client.add_comment(
            question_bead_id,
            f"Question timed out after {ctx.question_timeout}s. Agent proceeding with best judgment.",
        )
        return (
            f"Your question (bead {question_bead_id}) was not answered within the timeout period.\n\n"
            f"Please proceed with your best judgment to implement bead {ctx.bead_id}. "
            f"Document any assumptions you make as comments on the bead."
        )

    def _check_fatal_failure(self, ctx: PipelineContext, oc_result: OpenCodeResult) -> None:
        """Raise if OpenCode exited with a non-recoverable error."""
        if oc_result.exit_code != 0 and not oc_result.timed_out and not oc_result.needs_answer_bead_id:
            ctx.client.add_comment(ctx.bead_id, f"OpenCode failed with exit code {oc_result.exit_code}")
            raise RuntimeError(f"OpenCode failed with exit code {oc_result.exit_code}")

    # -------------------------------------------------------------------
    # Phase 4: Deliver
    # -------------------------------------------------------------------

    def _phase_deliver(self, ctx: PipelineContext) -> None:
        """Cleanup, commit, push, create PR, update bead."""
        self._set_phase("deliver")

        cleanup_agents_md(ctx.workspace)

        bead_title = ctx.bead_data.get("title", f"implement {ctx.bead_id}")
        commit_msg = f"feat: {bead_title} ({ctx.bead_id})"
        has_changes = stage_and_commit(ctx.workspace, commit_msg)

        if not has_changes:
            self._finish_no_changes(ctx)
            return

        push_branch(ctx.workspace, ctx.branch_name)

        pr_url = self._create_and_record_pr(ctx, bead_title)

        self._create_review_bead(ctx, bead_title, pr_url)

        ctx.client.sync_push()
        self._set_phase("complete")

        self.set_output_property("prUrl", pr_url)
        self.set_output_property("branchName", ctx.branch_name)
        self.set_output_property("beadStatus", "pr-created")
        self._comment(f"Done. PR: {pr_url}")

    def _finish_no_changes(self, ctx: PipelineContext) -> None:
        """Handle the case where the agent produced no code changes."""
        ctx.client.add_comment(ctx.bead_id, "Agent completed but produced no code changes.")
        self.set_output_property("prUrl", "")
        self.set_output_property("branchName", ctx.branch_name)
        self.set_output_property("beadStatus", "no-changes")

    def _create_and_record_pr(self, ctx: PipelineContext, bead_title: str) -> str:
        """Create a GitHub PR and record it on the bead. Returns the PR URL."""
        bead_description = ctx.bead_data.get("description", f"See bead {ctx.bead_id} for details.")
        diff_stat = get_diff_stat(ctx.workspace)
        pr_body = self._build_pr_body(ctx.bead_id, bead_description, diff_stat)
        pr_title = f"{bead_title} ({ctx.bead_id})"

        pr_url = create_pr(
            workspace_dir=ctx.workspace,
            title=pr_title,
            body=pr_body,
            base_branch=ctx.repo_branch,
            head_branch=ctx.branch_name,
            github_token=ctx.github_token,
        )

        ctx.client.update_bead(ctx.bead_id, notes=f"PR: {pr_url}")
        ctx.client.add_comment(ctx.bead_id, f"Pull request created: {pr_url}")
        return pr_url

    def _create_review_bead(self, ctx: PipelineContext, bead_title: str, pr_url: str) -> None:
        """Create a review-request child bead for the PR."""
        review_bead = ctx.client.create_bead(
            title=f"Review: {bead_title}",
            description=f"PR ready for review: {pr_url}\n\nParent bead: {ctx.bead_id}",
            issue_type="task",
            priority=2,
            parent=ctx.bead_id,
        )
        if review_bead:
            logger.info(f"Review bead created: {review_bead.get('id', 'unknown')}")

    # -------------------------------------------------------------------
    # Shared helpers
    # -------------------------------------------------------------------

    def _build_llm_env(self, llm_server: Dict) -> Dict[str, str]:
        """Build environment variables for the LLM provider."""
        env = {}
        provider = llm_server.get("provider", "anthropic")
        api_key = llm_server.get("apiKey", "")

        if provider == "docker-model-runner":
            # Local model runner -- no API key env var needed
            pass
        elif provider == "anthropic":
            env["ANTHROPIC_API_KEY"] = api_key
        elif provider == "openai":
            env["OPENAI_API_KEY"] = api_key
        else:
            # Default to anthropic-style env var
            env["ANTHROPIC_API_KEY"] = api_key

        return env

    def _build_pr_body(self, bead_id: str, description: str, diff_stat: str) -> str:
        """Compose the pull request body markdown."""
        return (
            f"## Summary\n\n"
            f"Automated implementation for bead **{bead_id}**.\n\n"
            f"## Bead Description\n\n"
            f"{description}\n\n"
            f"## Changes\n\n"
            f"{diff_stat}\n\n"
            f"---\n\n"
            f"*This PR was created automatically by the Release Code Agent plugin. "
            f"Review the changes and provide feedback on the bead or this PR.*"
        )

    def _poll_for_answer(
        self,
        client: BeadsClient,
        question_bead_id: str,
        timeout: int,
        poll_interval: int = 30,
    ) -> Optional[str]:
        """
        Poll for an answer to a question bead.

        Returns the answer text, or None if timed out.
        Mirrors run-agent.sh poll_for_answer() function.
        """
        logger.info(f"Polling for answer to {question_bead_id} (timeout: {timeout}s)...")
        elapsed = 0

        while elapsed < timeout:
            time.sleep(poll_interval)
            elapsed += poll_interval
            client.sync_pull()

            answer = self._extract_answer_from_comments(client, question_bead_id)
            if answer:
                logger.info(f"Answer received for {question_bead_id} after {elapsed}s")
                return answer

            answer = self._extract_answer_from_closed_bead(client, question_bead_id)
            if answer:
                return answer

            logger.info(f"No answer yet for {question_bead_id} ({elapsed}s / {timeout}s)")

        logger.warning(f"Question timeout after {timeout}s for {question_bead_id}")
        return None

    def _extract_answer_from_comments(self, client: BeadsClient, question_bead_id: str) -> Optional[str]:
        """Check bead comments for an answer. Returns answer text or None."""
        comments = client.list_comments(question_bead_id)
        if not comments:
            return None
        latest = comments[-1]
        return latest.get("content") or latest.get("body") or latest.get("text") or None

    def _extract_answer_from_closed_bead(self, client: BeadsClient, question_bead_id: str) -> Optional[str]:
        """Check if the question bead was closed with notes (used as answer). Returns notes or None."""
        q_bead = client.show_bead(question_bead_id)
        if q_bead and q_bead.get("status") == "closed":
            notes = q_bead.get("notes", "")
            if notes:
                logger.info("Question bead was closed with notes -- treating as answer")
                return notes
        return None

    def _set_phase(self, phase: str) -> None:
        """Update the task status line in Release UI."""
        logger.info(f"Phase: {phase}")
        try:
            self.set_status_line(f"Phase: {phase}")
        except Exception:
            pass  # set_status_line may not be available in all contexts

    def _comment(self, message: str) -> None:
        """Add a comment to the Release task activity log."""
        logger.info(message)
        try:
            self.add_comment(message)
        except Exception:
            pass  # add_comment may not be available in all contexts
