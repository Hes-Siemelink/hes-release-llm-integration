"""
git_ops.py -- Git and GitHub CLI operations.

Ports the git/gh operations from beads-coder's setup.sh and deliver.sh
to Python subprocess calls. Handles auth, clone, branch, commit, push,
and PR creation.
"""

import os
import subprocess
from typing import List, Optional


def _run(
    cmd: List[str],
    cwd: Optional[str] = None,
    timeout: int = 300,
    check: bool = True,
    env: Optional[dict] = None,
) -> subprocess.CompletedProcess:
    """Run a shell command with logging and error handling."""
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
        print(f"Command failed (exit {result.returncode}): {result.stderr.strip()}")
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr
        )
    return result


# ---------------------------------------------------------------------------
# Git identity and auth
# ---------------------------------------------------------------------------


def configure_git(actor: str, email: str, github_token: str) -> None:
    """
    Configure git identity and GitHub authentication.

    Mirrors setup.sh lines 41-60.
    """
    print(f"Configuring git identity: {actor} <{email}>")
    _set_git_identity(actor, email)
    _set_git_token_rewrite(github_token)
    _verify_gh_auth(github_token)


def _set_git_identity(actor: str, email: str) -> None:
    """Set global git user.name and user.email."""
    _run(["git", "config", "--global", "user.name", actor])
    _run(["git", "config", "--global", "user.email", email])


def _set_git_token_rewrite(github_token: str) -> None:
    """Configure git to rewrite HTTPS URLs with an embedded token."""
    _run([
        "git", "config", "--global",
        f"url.https://{github_token}@github.com/.insteadOf",
        "https://github.com/",
    ])


def _verify_gh_auth(github_token: str) -> None:
    """Best-effort check that gh CLI can authenticate."""
    env = os.environ.copy()
    env["GITHUB_TOKEN"] = github_token
    result = _run(["gh", "auth", "status"], check=False, env=env)
    if result.returncode == 0:
        print("GitHub CLI authenticated via GITHUB_TOKEN env var.")
    else:
        print(f"GitHub CLI auth check returned non-zero: {result.stderr.strip()}")


# ---------------------------------------------------------------------------
# Clone and branch
# ---------------------------------------------------------------------------


def clone_repo(repo_url: str, workspace_dir: str, timeout: int = 600) -> None:
    """
    Clone a repository into the workspace directory.

    Mirrors setup.sh lines 143-154.
    """
    if os.path.isdir(os.path.join(workspace_dir, ".git")):
        print("Workspace already contains a git repo -- using existing clone")
        return

    print(f"Cloning {repo_url} into {workspace_dir}...")
    _run(["git", "clone", repo_url, workspace_dir], timeout=timeout)
    print("Clone complete.")


def create_branch(workspace_dir: str, branch_name: str, base_branch: str = "main") -> None:
    """
    Create and checkout a feature branch from the base branch.

    Mirrors setup.sh lines 165-173.
    """
    print(f"Creating branch {branch_name} from origin/{base_branch}")
    _run(
        ["git", "checkout", "-b", branch_name, f"origin/{base_branch}"],
        cwd=workspace_dir,
    )


# ---------------------------------------------------------------------------
# Stage, commit, push
# ---------------------------------------------------------------------------


DEFAULT_EXCLUDE_PATTERNS = ["AGENTS.md", ".beads", "opencode.json"]


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
        exclude_patterns = DEFAULT_EXCLUDE_PATTERNS

    _revert_excluded_files(workspace_dir, exclude_patterns)

    if not _has_uncommitted_changes(workspace_dir):
        print("No changes detected in workspace")
        return False

    _stage_all_except(workspace_dir, exclude_patterns)

    if not _has_staged_changes(workspace_dir):
        print("No changes remain after excluding orchestrator artifacts")
        return False

    print(f"Committing: {commit_message}")
    _run(["git", "commit", "-m", commit_message], cwd=workspace_dir)
    return True


def _revert_excluded_files(workspace_dir: str, patterns: List[str]) -> None:
    """Restore excluded files to their HEAD state so they won't be committed."""
    for pattern in patterns:
        _run(["git", "checkout", "--", pattern], cwd=workspace_dir, check=False)
        _run(["git", "restore", "--staged", pattern], cwd=workspace_dir, check=False)
        _run(["git", "rm", "--cached", pattern], cwd=workspace_dir, check=False)


def _has_uncommitted_changes(workspace_dir: str) -> bool:
    """Check whether the workspace has any diff or untracked files."""
    diff_result = _run(["git", "diff", "--stat", "HEAD"], cwd=workspace_dir, check=False)
    untracked_result = _run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=workspace_dir,
        check=False,
    )

    diff_stat = diff_result.stdout.strip()
    untracked = untracked_result.stdout.strip()

    if diff_stat:
        print(f"Changes detected:\n{diff_stat}")
    if untracked:
        print(f"Untracked files:\n{untracked}")

    return bool(diff_stat or untracked)


def _stage_all_except(workspace_dir: str, patterns: List[str]) -> None:
    """Stage everything, then unstage the excluded patterns."""
    _run(["git", "add", "-A"], cwd=workspace_dir)
    for pattern in patterns:
        _run(["git", "reset", "HEAD", "--", pattern], cwd=workspace_dir, check=False)


def _has_staged_changes(workspace_dir: str) -> bool:
    """Return True if there are staged changes ready to commit."""
    result = _run(["git", "diff", "--cached", "--quiet"], cwd=workspace_dir, check=False)
    return result.returncode != 0  # non-zero means there are staged changes


def push_branch(workspace_dir: str, branch_name: str, timeout: int = 300) -> None:
    """
    Push a branch to origin.

    Mirrors deliver.sh lines 84-89.
    """
    print(f"Pushing branch {branch_name} to origin...")
    _run(
        ["git", "push", "-u", "origin", branch_name],
        cwd=workspace_dir,
        timeout=timeout,
    )
    print("Push complete.")


# ---------------------------------------------------------------------------
# Pull request
# ---------------------------------------------------------------------------


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
    print("Creating pull request...")
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
    print(f"PR created: {pr_url}")
    return pr_url


# ---------------------------------------------------------------------------
# Diff utilities
# ---------------------------------------------------------------------------


def get_diff_stat(workspace_dir: str, ref: str = "HEAD~1 HEAD") -> str:
    """Get git diff --stat for the last commit."""
    parts = ref.split()
    result = _run(
        ["git", "diff", "--stat"] + parts,
        cwd=workspace_dir,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "See commits for details."
