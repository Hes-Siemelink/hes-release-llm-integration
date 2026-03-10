"""
agents_md.py -- AGENTS.md template injection for container workspaces.

Ports beads-coder's setup.sh AGENTS.md injection logic to Python.
Reads the container-AGENTS.md template from the resources directory,
substitutes placeholders, and injects it into the cloned workspace.
Also handles cleanup before commit.

Raises:
    FileNotFoundError: If container-AGENTS.md template is not found in any
        of the expected directories.
"""

import logging
import os
import shutil
from pathlib import Path
from string import Template
from typing import Optional

logger = logging.getLogger(__name__)

# Separator used when appending to an existing AGENTS.md
SEPARATOR = "\n\n---\n\n# Orchestrator Instructions (injected -- do not commit)\n\n"

# Backup suffix for the original AGENTS.md
BACKUP_SUFFIX = ".original"

# Default location of the template inside the container image
DEFAULT_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "resources")


def _find_template(template_dir: Optional[str] = None) -> str:
    """Locate the container-AGENTS.md template file.

    Args:
        template_dir: Optional override for template location.

    Returns:
        Path to the container-AGENTS.md template file.

    Raises:
        FileNotFoundError: If container-AGENTS.md template is not found in any
            of the expected directories.
    """
    search_dirs = []
    if template_dir:
        search_dirs.append(template_dir)
    search_dirs.append(DEFAULT_TEMPLATE_DIR)
    # Also check /app/resources (container layout)
    search_dirs.append("/app/resources")

    for d in search_dirs:
        path = os.path.join(d, "container-AGENTS.md")
        if os.path.isfile(path):
            return path

    raise FileNotFoundError(
        f"container-AGENTS.md not found in: {search_dirs}"
    )


def inject_agents_md(
    workspace_dir: str,
    bead_id: str,
    template_dir: Optional[str] = None,
) -> str:
    """Inject container-specific AGENTS.md instructions into the workspace.

    If the workspace already has an AGENTS.md, backs it up and appends
    the orchestrator instructions. If not, creates a new one.

    Args:
        workspace_dir: Path to the cloned repo workspace.
        bead_id: The bead ID to substitute into the template.
        template_dir: Optional override for template location.

    Returns:
        Path to the written AGENTS.md file.

    Raises:
        FileNotFoundError: If the template file cannot be found.
        IOError: If there are issues reading or writing files.
    """
    template_path = _find_template(template_dir)

    with open(template_path, "r") as f:
        template_content = f.read()

    # Substitute ${BEAD_ID} placeholder
    rendered = template_content.replace("${BEAD_ID}", bead_id)

    agents_md_path = os.path.join(workspace_dir, "AGENTS.md")
    backup_path = agents_md_path + BACKUP_SUFFIX

    if os.path.isfile(agents_md_path):
        # Back up the original
        shutil.copy2(agents_md_path, backup_path)
        logger.info(f"Backed up existing AGENTS.md to {backup_path}")

        # Append orchestrator instructions
        with open(agents_md_path, "a") as f:
            f.write(SEPARATOR)
            f.write(rendered)
        logger.info(f"Appended orchestrator instructions to {agents_md_path}")
    else:
        # Create new AGENTS.md with just the orchestrator instructions
        with open(agents_md_path, "w") as f:
            f.write(rendered)
        logger.info(f"Created {agents_md_path} with orchestrator instructions")

    return agents_md_path


def cleanup_agents_md(workspace_dir: str) -> None:
    """Restore the original AGENTS.md before committing.

    If a backup exists, restores it. If no backup (meaning we created the
    file from scratch), removes it entirely so the commit doesn't include
    orchestrator artifacts.

    Args:
        workspace_dir: Path to the cloned repo workspace.
    """
    agents_md_path = os.path.join(workspace_dir, "AGENTS.md")
    backup_path = agents_md_path + BACKUP_SUFFIX

    if os.path.isfile(backup_path):
        # Restore original
        shutil.move(backup_path, agents_md_path)
        logger.info(f"Restored original AGENTS.md from backup")
    elif os.path.isfile(agents_md_path):
        # We created it from scratch -- remove it
        os.remove(agents_md_path)
        logger.info(f"Removed injected AGENTS.md (no original existed)")
    else:
        logger.debug("No AGENTS.md to clean up")


def inject_opencode_config(
    workspace_dir: str,
    template_dir: Optional[str] = None,
) -> str:
    """Copy container-opencode.json into the workspace as opencode.json.

    This ensures OpenCode runs with permission: allow in the container.

    Args:
        workspace_dir: Path to the cloned repo workspace.
        template_dir: Optional override for template location.

    Returns:
        Path to the written opencode.json file.

    Raises:
        FileNotFoundError: If the template file cannot be found.
        IOError: If there are issues reading or writing files.
    """
    search_dirs = []
    if template_dir:
        search_dirs.append(template_dir)
    search_dirs.append(DEFAULT_TEMPLATE_DIR)
    search_dirs.append("/app/resources")

    src_path = None
    for d in search_dirs:
        path = os.path.join(d, "container-opencode.json")
        if os.path.isfile(path):
            src_path = path
            break

    if src_path is None:
        raise FileNotFoundError(
            f"container-opencode.json not found in: {search_dirs}"
        )

    dest_path = os.path.join(workspace_dir, "opencode.json")
    shutil.copy2(src_path, dest_path)
    logger.info(f"Copied opencode.json to {dest_path}")
    return dest_path
