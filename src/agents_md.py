"""
agents_md.py -- AGENTS.md template injection for container workspaces.

Ports beads-coder's setup.sh AGENTS.md injection logic to Python.
Reads the container-AGENTS.md template from the resources directory,
substitutes placeholders, and injects it into the cloned workspace.
Also handles cleanup before commit.
"""

import json
import logging
import os
import shutil
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Separator used when appending to an existing AGENTS.md
SEPARATOR = "\n\n---\n\n# Orchestrator Instructions (injected -- do not commit)\n\n"

# Backup suffix for the original AGENTS.md
BACKUP_SUFFIX = ".original"

# Default location of the template inside the container image
DEFAULT_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "resources")

# Search order for resource files
_CONTAINER_RESOURCE_DIR = "/app/resources"


def _find_resource(filename: str, template_dir: Optional[str] = None) -> str:
    """Locate a resource file by searching standard directories.

    Raises FileNotFoundError if the file cannot be found.
    """
    search_dirs = []
    if template_dir:
        search_dirs.append(template_dir)
    search_dirs.append(DEFAULT_TEMPLATE_DIR)
    search_dirs.append(_CONTAINER_RESOURCE_DIR)

    for d in search_dirs:
        path = os.path.join(d, filename)
        if os.path.isfile(path):
            return path

    raise FileNotFoundError(f"{filename} not found in: {search_dirs}")


# ---------------------------------------------------------------------------
# AGENTS.md injection / cleanup
# ---------------------------------------------------------------------------


def inject_agents_md(
    workspace_dir: str,
    bead_id: str,
    template_dir: Optional[str] = None,
) -> str:
    """
    Inject container-specific AGENTS.md instructions into the workspace.

    If the workspace already has an AGENTS.md, backs it up and appends
    the orchestrator instructions. If not, creates a new one.

    Returns:
        Path to the written AGENTS.md file.
    """
    template_path = _find_resource("container-AGENTS.md", template_dir)
    rendered = _render_template(template_path, bead_id)

    agents_md_path = os.path.join(workspace_dir, "AGENTS.md")
    _write_agents_md(agents_md_path, rendered)
    return agents_md_path


def _render_template(template_path: str, bead_id: str) -> str:
    """Read template and substitute ${BEAD_ID} placeholders."""
    with open(template_path, "r") as f:
        content = f.read()
    return content.replace("${BEAD_ID}", bead_id)


def _write_agents_md(agents_md_path: str, rendered: str) -> None:
    """Write the rendered content, backing up any existing file."""
    backup_path = agents_md_path + BACKUP_SUFFIX

    if os.path.isfile(agents_md_path):
        shutil.copy2(agents_md_path, backup_path)
        logger.info(f"Backed up existing AGENTS.md to {backup_path}")

        with open(agents_md_path, "a") as f:
            f.write(SEPARATOR)
            f.write(rendered)
        logger.info(f"Appended orchestrator instructions to {agents_md_path}")
    else:
        with open(agents_md_path, "w") as f:
            f.write(rendered)
        logger.info(f"Created {agents_md_path} with orchestrator instructions")


def cleanup_agents_md(workspace_dir: str) -> None:
    """
    Restore the original AGENTS.md before committing.

    If a backup exists, restores it. If no backup (meaning we created the
    file from scratch), removes it entirely so the commit doesn't include
    orchestrator artifacts.
    """
    agents_md_path = os.path.join(workspace_dir, "AGENTS.md")
    backup_path = agents_md_path + BACKUP_SUFFIX

    if os.path.isfile(backup_path):
        shutil.move(backup_path, agents_md_path)
        logger.info("Restored original AGENTS.md from backup")
    elif os.path.isfile(agents_md_path):
        os.remove(agents_md_path)
        logger.info("Removed injected AGENTS.md (no original existed)")
    else:
        logger.debug("No AGENTS.md to clean up")


# ---------------------------------------------------------------------------
# OpenCode config injection
# ---------------------------------------------------------------------------


def inject_opencode_config(
    workspace_dir: str,
    template_dir: Optional[str] = None,
    llm_server: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Copy container-opencode.json into the workspace as opencode.json.

    If llm_server provides a URL for docker-model-runner, updates the
    baseURL in the provider config so OpenCode can reach the endpoint.

    Returns:
        Path to the written opencode.json file.
    """
    src_path = _find_resource("container-opencode.json", template_dir)
    dest_path = os.path.join(workspace_dir, "opencode.json")

    config = _load_opencode_template(src_path)
    if llm_server:
        _apply_llm_server_url(config, llm_server)
    _write_json(dest_path, config)

    logger.info(f"Wrote opencode.json to {dest_path}")
    return dest_path


def _load_opencode_template(path: str) -> Dict[str, Any]:
    """Read the opencode config template as a dict."""
    with open(path, "r") as f:
        return json.load(f)


def _apply_llm_server_url(config: Dict[str, Any], llm_server: Dict[str, Any]) -> None:
    """Update the docker-model-runner baseURL if a URL is provided."""
    url = llm_server.get("url", "")
    if not url:
        return

    provider = llm_server.get("provider", "")
    providers = config.get("provider", {})

    if provider == "docker-model-runner" and "docker-model-runner" in providers:
        providers["docker-model-runner"].setdefault("options", {})["baseURL"] = url
        logger.info(f"Set docker-model-runner baseURL to {url}")


def _write_json(path: str, data: Dict[str, Any]) -> None:
    """Write a dict as formatted JSON."""
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
