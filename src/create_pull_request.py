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
import os
import time
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
        props = self.input_properties

        # Extract inputs
        beads_server = props.get("beadsServer", {})
        bead_id = props.get("beadId", "")
        repo_url = props.get("repoUrl", "")
        repo_branch = props.get("repoBranch", "main")
        github_token = props.get("githubToken", "")
        llm_server = props.get("llmServer", {})
        opencode_timeout = int(props.get("opencodeTimeout", 1800))
        question_timeout = int(props.get("questionTimeout", 3600))
        max_question_rounds = int(props.get("maxQuestionRounds", 5))

        workspace = DEFAULT_WORKSPACE

        # Validate required inputs
        self._validate_inputs(bead_id, repo_url, github_token, beads_server, llm_server)

        # ---------------------------------------------------------------
        # Phase 1: Setup
        # ---------------------------------------------------------------
        self._set_phase("setup")

        # Init beads client
        client = BeadsClient.from_server_properties(beads_server)
        client.init_metadata()
        self._comment(f"Starting work on bead {bead_id}")

        # Read bead data
        bead_data = client.show_bead(bead_id)
        if bead_data is None:
            raise RuntimeError(f"Bead {bead_id} not found")

        # Configure git auth
        actor = beads_server.get("actor", "beads-coder")
        configure_git(actor, f"{actor}@release.digital.ai", github_token)

        # Clone repo and create feature branch
        clone_repo(repo_url, workspace)
        branch_name = f"beads/{bead_id}"
        create_branch(workspace, branch_name, repo_branch)

        # Claim the bead
        client.update_bead(bead_id, status="in_progress")
        client.add_comment(bead_id, f"Claimed by Release task. Branch: {branch_name}")

        # Inject AGENTS.md with bead context
        inject_agents_md(workspace, bead_id)

        self._set_phase("setup-complete")

        # ---------------------------------------------------------------
        # Phase 2: Code
        # ---------------------------------------------------------------
        self._set_phase("code")

        prompt = compose_prompt(bead_data)
        llm_env = self._build_llm_env(llm_server)
        model = llm_server.get("model") or None

        oc_result = run_opencode(
            prompt=prompt,
            workspace_dir=workspace,
            model=model,
            timeout=opencode_timeout,
            llm_env=llm_env,
        )

        if oc_result.timed_out:
            client.add_comment(bead_id, f"OpenCode timed out after {opencode_timeout}s")

        # ---------------------------------------------------------------
        # Phase 3: Question loop
        # ---------------------------------------------------------------
        question_round = 0

        while oc_result.needs_answer_bead_id:
            question_round += 1

            if question_round > max_question_rounds:
                client.add_comment(
                    bead_id,
                    f"Max question rounds ({max_question_rounds}) exceeded. Proceeding with best judgment.",
                )
                break

            self._set_phase(f"question-loop-{question_round}")

            question_bead_id = oc_result.needs_answer_bead_id
            logger.info(f"Question detected: {question_bead_id} (round {question_round})")

            # Sync push so the question is visible upstream
            client.sync_push()

            # Poll for answer
            answer = self._poll_for_answer(client, question_bead_id, question_timeout)

            if answer:
                resume_prompt = (
                    f"The answer to your question (bead {question_bead_id}) is:\n\n"
                    f"{answer}\n\n"
                    f"Please continue implementing bead {bead_id} based on this answer."
                )
            else:
                resume_prompt = (
                    f"Your question (bead {question_bead_id}) was not answered within the timeout period.\n\n"
                    f"Please proceed with your best judgment to implement bead {bead_id}. "
                    f"Document any assumptions you make as comments on the bead."
                )
                client.add_comment(
                    question_bead_id,
                    f"Question timed out after {question_timeout}s. Agent proceeding with best judgment.",
                )

            self._set_phase(f"code-resumed-{question_round}")

            oc_result = run_opencode(
                prompt=resume_prompt,
                workspace_dir=workspace,
                model=model,
                timeout=opencode_timeout,
                llm_env=llm_env,
            )

        # Check if OpenCode failed fatally (non-zero, no question, not timeout)
        if oc_result.exit_code != 0 and not oc_result.timed_out and not oc_result.needs_answer_bead_id:
            client.add_comment(bead_id, f"OpenCode failed with exit code {oc_result.exit_code}")
            raise RuntimeError(f"OpenCode failed with exit code {oc_result.exit_code}")

        client.add_comment(bead_id, f"Coding phase complete ({question_round} question round(s)).")

        # ---------------------------------------------------------------
        # Phase 4: Deliver
        # ---------------------------------------------------------------
        self._set_phase("deliver")

        # Cleanup orchestrator artifacts before commit
        cleanup_agents_md(workspace)

        # Stage and commit
        bead_title = bead_data.get("title", f"implement {bead_id}")
        commit_msg = f"feat: {bead_title} ({bead_id})"
        has_changes = stage_and_commit(workspace, commit_msg)

        if not has_changes:
            client.add_comment(bead_id, "Agent completed but produced no code changes.")
            self.set_output_property("prUrl", "")
            self.set_output_property("branchName", branch_name)
            self.set_output_property("beadStatus", "no-changes")
            return

        # Push branch
        push_branch(workspace, branch_name)

        # Create pull request
        bead_description = bead_data.get("description", f"See bead {bead_id} for details.")
        diff_stat = get_diff_stat(workspace)
        pr_body = self._build_pr_body(bead_id, bead_description, diff_stat)
        pr_title = f"{bead_title} ({bead_id})"

        pr_url = create_pr(
            workspace_dir=workspace,
            title=pr_title,
            body=pr_body,
            base_branch=repo_branch,
            head_branch=branch_name,
            github_token=github_token,
        )

        # Update bead with PR reference
        client.update_bead(bead_id, notes=f"PR: {pr_url}")
        client.add_comment(bead_id, f"Pull request created: {pr_url}")

        # Create review-request child bead
        review_bead = client.create_bead(
            title=f"Review: {bead_title}",
            description=f"PR ready for review: {pr_url}\n\nParent bead: {bead_id}",
            issue_type="task",
            priority=2,
            parent=bead_id,
        )
        if review_bead:
            logger.info(f"Review bead created: {review_bead.get('id', 'unknown')}")

        # Final sync
        client.sync_push()

        self._set_phase("complete")

        # Set output properties
        self.set_output_property("prUrl", pr_url)
        self.set_output_property("branchName", branch_name)
        self.set_output_property("beadStatus", "pr-created")

        self._comment(f"Done. PR: {pr_url}")

    # -------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------

    def _validate_inputs(
        self,
        bead_id: str,
        repo_url: str,
        github_token: str,
        beads_server: Dict,
        llm_server: Dict,
    ) -> None:
        """Validate required input properties."""
        if not bead_id:
            raise ValueError("Bead ID is required")
        if not repo_url:
            raise ValueError("Repository URL is required")
        if not github_token:
            raise ValueError("GitHub token is required")
        if not beads_server.get("projectId"):
            raise ValueError("Beads Server Project ID is required")
        if not llm_server.get("apiKey"):
            raise ValueError("LLM API key is required")

    def _build_llm_env(self, llm_server: Dict) -> Dict[str, str]:
        """Build environment variables for the LLM provider."""
        env = {}
        provider = llm_server.get("provider", "anthropic")
        api_key = llm_server.get("apiKey", "")

        if provider == "anthropic":
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

            # Pull latest state
            client.sync_pull()

            # Check for comments (answers)
            comments = client.list_comments(question_bead_id)
            if comments:
                # Get the latest comment as the answer
                latest = comments[-1]
                answer = (
                    latest.get("content")
                    or latest.get("body")
                    or latest.get("text")
                    or ""
                )
                if answer:
                    logger.info(f"Answer received for {question_bead_id} after {elapsed}s")
                    return answer

            # Check if the question bead was closed with notes
            q_bead = client.show_bead(question_bead_id)
            if q_bead and q_bead.get("status") == "closed":
                notes = q_bead.get("notes", "")
                if notes:
                    logger.info("Question bead was closed with notes -- treating as answer")
                    return notes

            logger.info(f"No answer yet for {question_bead_id} ({elapsed}s / {timeout}s)")

        logger.warning(f"Question timeout after {timeout}s for {question_bead_id}")
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
