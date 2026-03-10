"""
git_ops.py -- Git and GitHub CLI operations.

Ports the git/gh operations from beads-coder's setup.sh and deliver.sh
to Python subprocess calls. Handles auth, clone, branch, commit, push,
and PR creation.
"""

import logging
import os
import subprocess
from typing import List, Optional

logger = logging.getLogger(__name__)


def _run(
    cmd: List[str],
    cwd: Optional[str] = None,
    timeout: int = 300,
    check: bool = True,
    env: Optional[dict] = None,
) -> subprocess.CompletedProcess:
    """Run a shell command with logging and error handling."""
    logger.debug(f"Running: {' '.join(cmd)} (cwd={cwd})")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=timeout,
        env=env or os.environ.copy(),
        check=False,
    )
    if check and result.returncode != 0:
        logger.error(f"Command failed (exit {result.returncode}): {result.stderr.strip()}")
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr
        )
    return result


def configure_git(actor: str, email: str, github_token: str) -> None:
    """
    Configure git identity and GitHub authentication.

    Mirrors setup.sh lines 41-60.
    """
    logger.info(f"Configuring git identity: {actor} <{email}>")
    _run(["git", "config", "--global", "user.name", actor])
    _run(["git", "config", "--global", "user.email", email])

    # Configure git to use HTTPS with token for clone/push
    _run([
        "git", "config", "--global",
        f"url.https://{github_token}@github.com/.insteadOf",
        "https://github.com/",
    ])

    # Verify gh auth via GITHUB_TOKEN env var
    env = os.environ.copy()
    env["GITHUB_TOKEN"] = github_token
    result = _run(["gh", "auth", "status"], check=False, env=env)
    if result.returncode == 0:
        logger.info("GitHub CLI authenticated via GITHUB_TOKEN env var.")
    else:
        logger.warning(f"GitHub CLI auth check returned non-zero: {result.stderr.strip()}")


def clone_repo(repo_url: str, workspace_dir: str, timeout: int = 600) -> None:
    """
    Clone a repository into the workspace directory.

    Mirrors setup.sh lines 143-154.
    """
    if os.path.isdir(os.path.join(workspace_dir, ".git")):
        logger.warning("Workspace already contains a git repo -- using existing clone")
        return

    logger.info(f"Cloning {repo_url} into {workspace_dir}...")
    _run(["git", "clone", repo_url, workspace_dir], timeout=timeout)
    logger.info("Clone complete.")


def create_branch(workspace_dir: str, branch_name: str, base_branch: str = "main") -> None:
    """
    Create and checkout a feature branch from the base branch.

    Mirrors setup.sh lines 165-173.
    """
    logger.info(f"Creating branch {branch_name} from origin/{base_branch}")
    _run(
        ["git", "checkout", "-b", branch_name, f"origin/{base_branch}"],
        cwd=workspace_dir,
    )


def stage_and_commit(
    workspace_dir: str,
    commit_message: str,
    exclude_patterns: Optional[List[str]] = None,
) -> bool:
    """
    Stage all changes and commit, excluding orchestrator artifacts.

    Returns True if a commit was made, False if no changes.
    Mirrors deliver.sh lines 26-79.
    """
    if exclude_patterns is None:
        exclude_patterns = ["AGENTS.md", ".beads"]

    # First, restore orchestrator artifacts to their original state
    for pattern in exclude_patterns:
        _run(["git", "checkout", "--", pattern], cwd=workspace_dir, check=False)
        _run(["git", "restore", "--staged", pattern], cwd=workspace_dir, check=False)
        _run(["git", "rm", "--cached", pattern], cwd=workspace_dir, check=False)

    # Check for actual changes
    diff_result = _run(["git", "diff", "--stat", "HEAD"], cwd=workspace_dir, check=False)
    untracked_result = _run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=workspace_dir,
        check=False,
    )

    diff_stat = diff_result.stdout.strip()
    untracked = untracked_result.stdout.strip()

    if not diff_stat and not untracked:
        logger.warning("No changes detected in workspace")
        return False

    logger.info(f"Changes detected:\n{diff_stat}")
    if untracked:
        logger.info(f"Untracked files:\n{untracked}")

    # Stage all
    _run(["git", "add", "-A"], cwd=workspace_dir)

    # Unstage orchestrator artifacts
    for pattern in exclude_patterns:
        _run(["git", "reset", "HEAD", "--", pattern], cwd=workspace_dir, check=False)

    # Verify there's still something staged
    staged_check = _run(
        ["git", "diff", "--cached", "--quiet"], cwd=workspace_dir, check=False
    )
    if staged_check.returncode == 0:
        logger.warning("No changes remain after excluding orchestrator artifacts")
        return False

    # Commit
    logger.info(f"Committing: {commit_message}")
    _run(["git", "commit", "-m", commit_message], cwd=workspace_dir)
    return True


def push_branch(workspace_dir: str, branch_name: str, timeout: int = 300) -> None:
    """
    Push a branch to origin.

    Mirrors deliver.sh lines 84-89.
    """
    logger.info(f"Pushing branch {branch_name} to origin...")
    _run(
        ["git", "push", "-u", "origin", branch_name],
        cwd=workspace_dir,
        timeout=timeout,
    )
    logger.info("Push complete.")


def create_pr(
    workspace_dir: str,
    title: str,
    body: str,
    base_branch: str,
    head_branch: str,
    github_token: str,
) -> str:
    """
    Create a pull request via GitHub CLI.

    Returns the PR URL.
    Mirrors deliver.sh lines 93-128.
    """
    logger.info("Creating pull request...")
    env = os.environ.copy()
    env["GITHUB_TOKEN"] = github_token

    result = _run(
        [
            "gh", "pr", "create",
            "--title", title,
            "--body", body,
            "--base", base_branch,
            "--head", head_branch,
        ],
        cwd=workspace_dir,
        env=env,
    )

    pr_url = result.stdout.strip()
    logger.info(f"PR created: {pr_url}")
    return pr_url


def get_diff_stat(workspace_dir: str, ref: str = "HEAD~1 HEAD") -> str:
    """Get git diff --stat for the last commit."""
    parts = ref.split()
    result = _run(
        ["git", "diff", "--stat"] + parts,
        cwd=workspace_dir,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "See commits for details."
