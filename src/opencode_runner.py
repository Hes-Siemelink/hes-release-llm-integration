"""
opencode_runner.py -- OpenCode headless invocation.

Ports beads-coder's run-agent.sh prompt composition and OpenCode
invocation to Python. Handles environment setup, timeout, output
capture, and the needs-answer signal file detection.
"""

import os
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional

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

    sections = [f"You are working on bead {bead_id}: {title}\n\n## Story\n\n{description}"]

    design = bead_data.get("design") or ""
    if design:
        sections.append(f"## Design Notes\n\n{design}")

    notes = bead_data.get("notes") or ""
    if notes:
        sections.append(f"## Additional Notes\n\n{notes}")

    sections.append(
        "## Instructions\n\n"
        "1. Read the AGENTS.md file in this workspace for project-specific guidance.\n"
        "2. Implement the changes described in the story above.\n"
        "3. Run any available tests to verify your work.\n"
        "4. If you are blocked and need human input, follow the question protocol in AGENTS.md.\n"
        "5. Do NOT commit or push -- the orchestrator handles that.\n"
        "6. When done, simply exit."
    )

    return "\n\n".join(sections)


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
    _clear_signal_file()

    env = _build_env(opencode_config, llm_env)
    cmd = _build_cmd(prompt, workspace_dir, model)

    print(f"Invoking OpenCode (timeout={timeout}s)...")
    print(f"Command: {' '.join(cmd[:6])}...")  # Don't log full prompt

    exit_code, output, timed_out = _invoke(cmd, workspace_dir, env, timeout)

    needs_answer_bead_id = _check_needs_answer()

    print(f"OpenCode exited with code {exit_code}")
    if needs_answer_bead_id:
        print(f"Question detected: bead {needs_answer_bead_id}")

    return OpenCodeResult(
        exit_code=exit_code,
        output=output,
        timed_out=timed_out,
        needs_answer_bead_id=needs_answer_bead_id,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clear_signal_file() -> None:
    """Remove any previous needs-answer signal file."""
    try:
        os.remove(NEEDS_ANSWER_FILE)
    except FileNotFoundError:
        pass


def _build_env(opencode_config: str, llm_env: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Build the environment dict for the OpenCode subprocess."""
    env = os.environ.copy()
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    env["OPENCODE_DISABLE_LSP_DOWNLOAD"] = "1"
    env["OPENCODE_DISABLE_PRUNE"] = "1"
    env["OPENCODE_CONFIG"] = opencode_config
    if llm_env:
        env.update(llm_env)
    return env


def _build_cmd(prompt: str, workspace_dir: str, model: Optional[str]) -> List[str]:
    """Build the opencode CLI command list."""
    cmd = ["opencode", "run", prompt, "--dir", workspace_dir, "--print-logs"]
    if model:
        cmd.extend(["-m", model])
    return cmd


def _invoke(
    cmd: List[str],
    cwd: str,
    env: Dict[str, str],
    timeout: int,
) -> tuple:
    """Run the subprocess and return (exit_code, output, timed_out)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=cwd,
        )
        return result.returncode, result.stdout + result.stderr, False

    except subprocess.TimeoutExpired as e:
        stdout = str(e.stdout or "") if e.stdout else ""
        stderr = str(e.stderr or "") if e.stderr else ""
        print(f"OpenCode timed out after {timeout}s")
        return 124, stdout + stderr, True  # 124 matches bash timeout exit code


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
