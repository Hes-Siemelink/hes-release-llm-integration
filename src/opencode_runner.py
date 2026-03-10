"""
opencode_runner.py -- OpenCode headless invocation.

Ports beads-coder's run-agent.sh prompt composition and OpenCode
invocation to Python. Handles environment setup, timeout, output
capture, and the needs-answer signal file detection.
"""

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Signal file path (written by OpenCode via AGENTS.md instructions)
NEEDS_ANSWER_FILE = "/tmp/needs-answer"

# Default OpenCode config path inside the container
DEFAULT_OPENCODE_CONFIG = "/app/opencode.json"


@dataclass
class OpenCodeResult:
    """Result of an OpenCode run."""
    exit_code: int
    output: str
    timed_out: bool = False
    needs_answer_bead_id: Optional[str] = None


def compose_prompt(bead_data: Dict) -> str:
    """
    Build the structured prompt from bead data.

    Mirrors run-agent.sh lines 51-82.

    Args:
        bead_data: Dict with keys: id, title, description, design (optional), notes (optional)
    """
    bead_id = bead_data.get("id", "unknown")
    title = bead_data.get("title", "Untitled")
    description = bead_data.get("description", "")

    prompt = f"""You are working on bead {bead_id}: {title}

## Story

{description}"""

    design = bead_data.get("design") or ""
    if design:
        prompt += f"""

## Design Notes

{design}"""

    notes = bead_data.get("notes") or ""
    if notes:
        prompt += f"""

## Additional Notes

{notes}"""

    prompt += """

## Instructions

1. Read the AGENTS.md file in this workspace for project-specific guidance.
2. Implement the changes described in the story above.
3. Run any available tests to verify your work.
4. If you are blocked and need human input, follow the question protocol in AGENTS.md.
5. Do NOT commit or push -- the orchestrator handles that.
6. When done, simply exit."""

    return prompt


def run_opencode(
    prompt: str,
    workspace_dir: str,
    model: Optional[str] = None,
    timeout: int = 1800,
    opencode_config: str = DEFAULT_OPENCODE_CONFIG,
    llm_env: Optional[Dict[str, str]] = None,
) -> OpenCodeResult:
    """
    Invoke OpenCode in headless mode.

    Mirrors run-agent.sh lines 108-178.

    Args:
        prompt: The prompt to send to OpenCode
        workspace_dir: The directory to operate in
        model: Optional model identifier
        timeout: Max seconds for OpenCode to run
        opencode_config: Path to opencode.json config
        llm_env: Additional environment variables (API keys, etc.)

    Returns:
        OpenCodeResult with exit code, output, and needs-answer info
    """
    # Clear any previous needs-answer signal
    try:
        os.remove(NEEDS_ANSWER_FILE)
    except FileNotFoundError:
        pass

    # Build environment
    env = os.environ.copy()
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    env["OPENCODE_DISABLE_LSP_DOWNLOAD"] = "1"
    env["OPENCODE_DISABLE_PRUNE"] = "1"
    env["OPENCODE_CONFIG"] = opencode_config

    if llm_env:
        env.update(llm_env)

    # Build command
    cmd = ["opencode", "run", prompt, "--dir", workspace_dir, "--print-logs"]
    if model:
        cmd.extend(["-m", model])

    logger.info(f"Invoking OpenCode (timeout={timeout}s)...")
    logger.debug(f"Command: {' '.join(cmd[:6])}...")  # Don't log full prompt

    output = ""
    timed_out = False
    exit_code = 0

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=workspace_dir,
        )
        exit_code = result.returncode
        output = result.stdout + result.stderr

    except subprocess.TimeoutExpired as e:
        timed_out = True
        exit_code = 124  # Match bash timeout exit code
        output = (e.stdout or "") + (e.stderr or "") if hasattr(e, "stdout") else ""
        logger.warning(f"OpenCode timed out after {timeout}s")

    # Check for needs-answer signal
    needs_answer_bead_id = _check_needs_answer()

    logger.info(f"OpenCode exited with code {exit_code}")
    if needs_answer_bead_id:
        logger.info(f"Question detected: bead {needs_answer_bead_id}")

    return OpenCodeResult(
        exit_code=exit_code,
        output=output,
        timed_out=timed_out,
        needs_answer_bead_id=needs_answer_bead_id,
    )


def _check_needs_answer() -> Optional[str]:
    """
    Check for the /tmp/needs-answer signal file.

    If OpenCode (via AGENTS.md instructions) created a question bead
    and wrote its ID to this file, return the bead ID.
    """
    try:
        with open(NEEDS_ANSWER_FILE, "r") as f:
            bead_id = f.read().strip()
            return bead_id if bead_id else None
    except FileNotFoundError:
        return None
