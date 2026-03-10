"""
opencode_runner.py -- OpenCode headless invocation.

Ports beads-coder's run-agent.sh prompt composition and OpenCode
invocation to Python. Handles environment setup, timeout, output
capture, and the needs-answer signal file detection.
"""

import os
import selectors
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
    print(f"Command: {' '.join(cmd)}")
    print(f"OPENCODE_CONFIG={env.get('OPENCODE_CONFIG', '(not set)')}")
    if env.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY=<set>")
    if env.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY=<set>")

    exit_code, output, timed_out = _invoke(cmd, workspace_dir, env, timeout)

    needs_answer_bead_id = _check_needs_answer()

    print(f"OpenCode exited with code {exit_code}")
    if not output.strip():
        print("OpenCode produced no output")
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
    cmd = ["opencode", "run", prompt, "--dir", workspace_dir]
    if model:
        cmd.extend(["-m", model])
    return cmd


def _invoke(
    cmd: List[str],
    cwd: str,
    env: Dict[str, str],
    timeout: int,
) -> tuple:
    """Run the subprocess, streaming output in real-time.

    Uses ``subprocess.Popen`` so that each line of stdout/stderr is
    printed (via ``print()``) as it arrives.  This makes OpenCode's
    progress visible in Release task logs during long runs instead of
    buffering everything until the process exits.

    Returns (exit_code, full_output, timed_out).
    """
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merge stderr into stdout
            text=True,
            env=env,
            cwd=cwd,
        )
    except Exception as e:
        print(f"Failed to start OpenCode: {e}")
        return 1, str(e), False

    lines: List[str] = []
    timed_out = False

    try:
        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ)  # type: ignore[arg-type]

        import time
        deadline = time.monotonic() + timeout

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                proc.kill()
                print(f"OpenCode timed out after {timeout}s")
                break

            events = sel.select(timeout=min(remaining, 1.0))
            for key, _ in events:
                line = key.fileobj.readline()  # type: ignore[union-attr]
                if line:
                    lines.append(line)
                    # Stream to stdout so Release captures it in real-time
                    print(line, end="", flush=True)
                else:
                    # EOF -- process has closed its stdout
                    sel.unregister(key.fileobj)  # type: ignore[arg-type]

            if not sel.get_map():
                # stdout closed, wait for process to finish
                break

        sel.close()
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
        proc.wait()

    exit_code = proc.returncode if proc.returncode is not None else 1
    output = "".join(lines)
    return exit_code, output, timed_out


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
