"""
beads_client.py -- Python wrapper for the bd (beads) CLI.

Ports the functionality of beads-coder's lib.sh to Python:
logging, exit codes, bead CRUD, comment operations, sync push/pull,
and metadata configuration. All bd CLI calls go through subprocess.
"""

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Exit codes (matching beads-coder lib.sh)
# ---------------------------------------------------------------------------
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_CONFIG_ERROR = 2
EXIT_CLAIM_CONFLICT = 3


@dataclass
class BeadsServerConfig:
    """Configuration for connecting to a beads server."""
    host: str = "beads-server"
    port: int = 3306
    project_id: str = ""
    prefix: str = "bc"
    sync_mode: str = "direct"  # "direct" or "dolt"
    actor: str = "beads-coder"


class BeadsClient:
    """
    Python client for the bd (beads) CLI.

    Wraps bd commands via subprocess.run() with proper error handling
    and timeout support. Mirrors the functionality from beads-coder's
    lib.sh and setup.sh.
    """

    def __init__(self, config: BeadsServerConfig, beads_dir: str = "/app/.beads"):
        self.config = config
        self.beads_dir = beads_dir
        self._env: Optional[Dict[str, str]] = None

    @classmethod
    def from_server_properties(cls, server: Dict[str, Any], beads_dir: str = "/app/.beads") -> "BeadsClient":
        """Create a BeadsClient from Release server configuration properties."""
        config = BeadsServerConfig(
            host=server.get("host", "beads-server"),
            port=int(server.get("port", 3306)),
            project_id=server.get("projectId", ""),
            prefix=server.get("prefix", "bc"),
            sync_mode=server.get("syncMode", "direct"),
            actor=server.get("actor", "beads-coder"),
        )
        return cls(config, beads_dir)

    def _get_env(self) -> Dict[str, str]:
        """Build environment dict for subprocess calls with BEADS_DIR set."""
        if self._env is None:
            self._env = os.environ.copy()
            self._env["BEADS_DIR"] = self.beads_dir
        return self._env

    def _run_bd(
        self,
        args: List[str],
        timeout: int = 30,
        capture_json: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        """
        Run a bd CLI command.

        Args:
            args: Arguments to pass to bd (e.g., ["show", "bc-42", "--json"])
            timeout: Command timeout in seconds
            capture_json: If True, append --json to args
            check: If True, raise on non-zero exit code
        """
        cmd = ["bd"] + args
        if capture_json and "--json" not in args:
            cmd.append("--json")

        print(f"Running: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=self._get_env(),
            check=False,
        )

        if check and result.returncode != 0:
            print(f"bd command failed (exit {result.returncode}): {result.stderr.strip()}")
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )

        return result

    def _parse_json_output(self, output: str) -> Any:
        """Parse JSON output from bd commands."""
        if not output.strip():
            return None
        try:
            return json.loads(output.strip())
        except json.JSONDecodeError as e:
            print(f"Failed to parse bd JSON output: {e}")
            return None

    # ---------------------------------------------------------------------------
    # Metadata / initialization
    # ---------------------------------------------------------------------------

    def init_metadata(self) -> None:
        """
        Create .beads/metadata.json for connecting to the beads server.

        Mirrors setup.sh lines 86-106: creates the minimal .beads directory
        with metadata pointing to the remote server, avoiding bd init entirely.
        """
        os.makedirs(self.beads_dir, exist_ok=True)

        metadata = {
            "database": "dolt",
            "backend": "dolt",
            "dolt_mode": "server",
            "dolt_database": self.config.prefix,
            "project_id": self.config.project_id,
            "dolt_server_host": self.config.host,
            "dolt_server_port": self.config.port,
            "dolt_server_user": "root",
            "issue_prefix": self.config.prefix,
        }

        metadata_path = os.path.join(self.beads_dir, "metadata.json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        # bd also reads the server port from this file
        port_path = os.path.join(self.beads_dir, "dolt-server.port")
        with open(port_path, "w") as f:
            f.write(str(self.config.port))

        print(f"Beads metadata written to {metadata_path}")

    # ---------------------------------------------------------------------------
    # Bead CRUD
    # ---------------------------------------------------------------------------

    def show_bead(self, bead_id: str) -> Optional[Dict[str, Any]]:
        """
        Read a bead by ID. Returns the bead dict or None if not found.

        Mirrors lib.sh bead_json() function.
        """
        try:
            result = self._run_bd(["show", bead_id, "--json"], check=False)
            if result.returncode != 0:
                print(f"Failed to show bead {bead_id}: {result.stderr.strip()}")
                return None
            data = self._parse_json_output(result.stdout)
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            return data
        except subprocess.TimeoutExpired:
            print(f"Timeout reading bead {bead_id}")
            return None

    def update_bead(self, bead_id: str, **kwargs) -> bool:
        """
        Update bead fields. Supported kwargs: status, assignee, notes, priority.

        Mirrors lib.sh bead_set_status() and setup.sh bead claiming.
        """
        args = ["update", bead_id]
        for key, value in kwargs.items():
            if value is not None:
                args.extend([f"--{key}", str(value)])

        try:
            self._run_bd(args, check=True)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"Failed to update bead {bead_id}: {e}")
            return False

    def create_bead(
        self,
        title: str,
        description: str = "",
        issue_type: str = "task",
        priority: int = 2,
        parent: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new bead. Returns the created bead dict or None on failure.

        Mirrors deliver.sh review bead creation.
        """
        args = ["create", title]
        if description:
            args.extend([f"--description={description}"])
        args.extend(["-t", issue_type, "-p", str(priority)])
        if parent:
            args.extend(["--parent", parent])
        args.append("--json")

        try:
            result = self._run_bd(args, check=True)
            data = self._parse_json_output(result.stdout)
            if isinstance(data, dict):
                return data
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            return data
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"Failed to create bead: {e}")
            return None

    def close_bead(self, bead_id: str, reason: str = "") -> bool:
        """Close a bead with an optional reason."""
        args = ["close", bead_id]
        if reason:
            args.extend(["--reason", reason])
        args.append("--force")

        try:
            self._run_bd(args, check=True)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"Failed to close bead {bead_id}: {e}")
            return False

    # ---------------------------------------------------------------------------
    # Comments
    # ---------------------------------------------------------------------------

    def add_comment(self, bead_id: str, message: str) -> bool:
        """
        Add a comment to a bead. Best-effort, never raises.

        Mirrors lib.sh bead_comment() function.
        """
        try:
            self._run_bd(["comments", "add", bead_id, message], check=False)
            return True
        except subprocess.TimeoutExpired:
            print(f"Timeout adding comment to {bead_id}")
            return False

    def list_comments(self, bead_id: str) -> List[Dict[str, Any]]:
        """
        List comments on a bead. Returns list of comment dicts.

        Used by the question polling loop.
        """
        try:
            result = self._run_bd(
                ["comments", "list", bead_id, "--json"], check=False
            )
            if result.returncode != 0:
                return []
            data = self._parse_json_output(result.stdout)
            return data if isinstance(data, list) else []
        except subprocess.TimeoutExpired:
            print(f"Timeout listing comments for {bead_id}")
            return []

    # ---------------------------------------------------------------------------
    # Sync
    # ---------------------------------------------------------------------------

    def sync_push(self) -> bool:
        """
        Push beads state upstream. Mode-dependent.

        Mirrors lib.sh beads_sync_push() function.
        """
        print(f"Pushing beads data (mode={self.config.sync_mode})...")

        if self.config.sync_mode == "direct":
            # Direct SQL: commit working set so changes are visible
            try:
                self._run_bd(["dolt", "commit"], check=False)
                print("Direct SQL mode -- committed working set.")
                return True
            except subprocess.TimeoutExpired:
                print("Timeout during dolt commit")
                return False

        elif self.config.sync_mode == "dolt":
            try:
                self._run_bd(["dolt", "commit"], check=False)
                self._run_bd(["dolt", "push"], check=True)
                print("Dolt push complete.")
                return True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                print(f"Dolt push failed: {e}")
                return False

        else:
            print(f"Unknown sync mode: {self.config.sync_mode}")
            return False

    def sync_pull(self) -> bool:
        """
        Pull beads data from upstream. Mode-dependent.

        Mirrors lib.sh beads_sync_pull() function.
        """
        print(f"Pulling beads data (mode={self.config.sync_mode})...")

        if self.config.sync_mode == "direct":
            # Direct SQL: no pull needed, reads go directly to shared DB
            print("Direct SQL mode -- no pull needed.")
            return True

        elif self.config.sync_mode == "dolt":
            try:
                self._run_bd(["dolt", "pull"], check=True)
                print("Dolt pull complete.")
                return True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                print(f"Dolt pull failed: {e}")
                return False

        else:
            print(f"Unknown sync mode: {self.config.sync_mode}")
            return False

    # ---------------------------------------------------------------------------
    # Utility
    # ---------------------------------------------------------------------------

    def test_connection(self) -> Tuple[bool, str]:
        """Test that bd can reach the beads server.

        Returns:
            Tuple of (success, detail_message).  On failure the message
            contains stderr / timeout info for diagnostics.
        """
        try:
            result = self._run_bd(["ready", "--json"], check=False)
            if result.returncode == 0:
                return True, "OK"
            detail = (result.stderr or result.stdout or "").strip()
            return False, f"bd exited {result.returncode}: {detail}"
        except subprocess.TimeoutExpired:
            return False, "bd timed out after 30 seconds"
