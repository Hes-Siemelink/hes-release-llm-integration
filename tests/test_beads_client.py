"""
Tests for beads_client.py -- BeadsClient wrapping the bd CLI.

All subprocess calls are mocked; no real bd binary is needed.
"""

import json
import os
import subprocess
import unittest
from unittest.mock import MagicMock, call, mock_open, patch

from src.beads_client import BeadsClient, BeadsServerConfig


class TestBeadsServerConfig(unittest.TestCase):
    """Test the BeadsServerConfig dataclass defaults."""

    def test_defaults(self):
        cfg = BeadsServerConfig()
        self.assertEqual(cfg.host, "beads-server")
        self.assertEqual(cfg.port, 3306)
        self.assertEqual(cfg.prefix, "bc")
        self.assertEqual(cfg.sync_mode, "direct")
        self.assertEqual(cfg.actor, "beads-coder")

    def test_custom_values(self):
        cfg = BeadsServerConfig(
            host="myhost", port=3307, project_id="proj-1",
            prefix="proj", sync_mode="dolt", actor="bot"
        )
        self.assertEqual(cfg.host, "myhost")
        self.assertEqual(cfg.port, 3307)
        self.assertEqual(cfg.project_id, "proj-1")


class TestBeadsClientInit(unittest.TestCase):
    """Test construction and from_server_properties."""

    def test_from_server_properties(self):
        props = {
            "host": "db.example.com",
            "port": 3307,
            "projectId": "proj-abc",
            "prefix": "abc",
            "syncMode": "dolt",
            "actor": "release-bot",
        }
        client = BeadsClient.from_server_properties(props)
        self.assertEqual(client.config.host, "db.example.com")
        self.assertEqual(client.config.port, 3307)
        self.assertEqual(client.config.project_id, "proj-abc")
        self.assertEqual(client.config.sync_mode, "dolt")

    def test_from_server_properties_defaults(self):
        client = BeadsClient.from_server_properties({})
        self.assertEqual(client.config.host, "beads-server")
        self.assertEqual(client.config.port, 3306)

    def test_get_env_sets_beads_dir(self):
        client = BeadsClient(BeadsServerConfig(), beads_dir="/custom/.beads")
        env = client._get_env()
        self.assertEqual(env["BEADS_DIR"], "/custom/.beads")


class TestInitMetadata(unittest.TestCase):
    """Test init_metadata writes correct files."""

    @patch("builtins.open", mock_open())
    @patch("os.makedirs")
    def test_creates_metadata_json(self, mock_makedirs):
        config = BeadsServerConfig(
            host="dbhost", port=3307, project_id="proj-1", prefix="pf"
        )
        client = BeadsClient(config, beads_dir="/tmp/test-beads")
        client.init_metadata()

        mock_makedirs.assert_called_once_with("/tmp/test-beads", exist_ok=True)

        # Check that open was called for metadata.json and dolt-server.port
        open_calls = [c[0][0] for c in open.call_args_list]
        self.assertIn("/tmp/test-beads/metadata.json", open_calls)
        self.assertIn("/tmp/test-beads/dolt-server.port", open_calls)


class TestShowBead(unittest.TestCase):
    """Test show_bead method."""

    def _make_client(self):
        return BeadsClient(BeadsServerConfig(), beads_dir="/tmp/.beads")

    @patch("subprocess.run")
    def test_show_bead_returns_dict(self, mock_run):
        bead_data = {"id": "bc-42", "title": "Fix login", "status": "open"}
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps([bead_data]), stderr=""
        )
        client = self._make_client()
        result = client.show_bead("bc-42")
        self.assertEqual(result["id"], "bc-42")
        self.assertEqual(result["title"], "Fix login")

    @patch("subprocess.run")
    def test_show_bead_not_found(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="not found"
        )
        client = self._make_client()
        result = client.show_bead("bc-999")
        self.assertIsNone(result)

    @patch("subprocess.run")
    def test_show_bead_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="bd", timeout=30)
        client = self._make_client()
        result = client.show_bead("bc-42")
        self.assertIsNone(result)


class TestUpdateBead(unittest.TestCase):
    """Test update_bead method."""

    def _make_client(self):
        return BeadsClient(BeadsServerConfig(), beads_dir="/tmp/.beads")

    @patch("subprocess.run")
    def test_update_bead_success(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        client = self._make_client()
        result = client.update_bead("bc-42", status="in_progress", assignee="bot")
        self.assertTrue(result)

        # Verify the command includes both --status and --assignee
        cmd = mock_run.call_args[0][0]
        self.assertIn("--status", cmd)
        self.assertIn("in_progress", cmd)
        self.assertIn("--assignee", cmd)
        self.assertIn("bot", cmd)

    @patch("subprocess.run")
    def test_update_bead_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="update failed"
        )
        client = self._make_client()
        result = client.update_bead("bc-42", status="closed")
        self.assertFalse(result)

    @patch("subprocess.run")
    def test_update_bead_skips_none_values(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        client = self._make_client()
        client.update_bead("bc-42", status="open", assignee=None)
        cmd = mock_run.call_args[0][0]
        self.assertIn("--status", cmd)
        self.assertNotIn("--assignee", cmd)


class TestCreateBead(unittest.TestCase):
    """Test create_bead method."""

    def _make_client(self):
        return BeadsClient(BeadsServerConfig(), beads_dir="/tmp/.beads")

    @patch("subprocess.run")
    def test_create_bead_success(self, mock_run):
        created = {"id": "bc-43", "title": "New task"}
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps(created), stderr=""
        )
        client = self._make_client()
        result = client.create_bead("New task", description="Details", priority=1)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "bc-43")

    @patch("subprocess.run")
    def test_create_bead_with_parent(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"id": "bc-44"}), stderr=""
        )
        client = self._make_client()
        client.create_bead("Sub-task", parent="bc-1")
        cmd = mock_run.call_args[0][0]
        self.assertIn("--parent", cmd)
        self.assertIn("bc-1", cmd)

    @patch("subprocess.run")
    def test_create_bead_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="create failed"
        )
        client = self._make_client()
        result = client.create_bead("Bad task")
        self.assertIsNone(result)


class TestCloseBead(unittest.TestCase):
    """Test close_bead method."""

    def _make_client(self):
        return BeadsClient(BeadsServerConfig(), beads_dir="/tmp/.beads")

    @patch("subprocess.run")
    def test_close_bead_success(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        client = self._make_client()
        result = client.close_bead("bc-42", reason="Implemented")
        self.assertTrue(result)

        cmd = mock_run.call_args[0][0]
        self.assertIn("--reason", cmd)
        self.assertIn("Implemented", cmd)
        self.assertIn("--force", cmd)

    @patch("subprocess.run")
    def test_close_bead_no_reason(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        client = self._make_client()
        client.close_bead("bc-42")
        cmd = mock_run.call_args[0][0]
        self.assertNotIn("--reason", cmd)
        self.assertIn("--force", cmd)

    @patch("subprocess.run")
    def test_close_bead_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="cannot close"
        )
        client = self._make_client()
        result = client.close_bead("bc-42")
        self.assertFalse(result)


class TestAddComment(unittest.TestCase):
    """Test add_comment method."""

    def _make_client(self):
        return BeadsClient(BeadsServerConfig(), beads_dir="/tmp/.beads")

    @patch("subprocess.run")
    def test_add_comment(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        client = self._make_client()
        result = client.add_comment("bc-42", "Progress update")
        self.assertTrue(result)

        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd, ["bd", "comments", "add", "bc-42", "Progress update"])

    @patch("subprocess.run")
    def test_add_comment_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="bd", timeout=30)
        client = self._make_client()
        result = client.add_comment("bc-42", "msg")
        self.assertFalse(result)


class TestListComments(unittest.TestCase):
    """Test list_comments method."""

    def _make_client(self):
        return BeadsClient(BeadsServerConfig(), beads_dir="/tmp/.beads")

    @patch("subprocess.run")
    def test_list_comments_returns_list(self, mock_run):
        comments = [
            {"id": 1, "message": "Started work"},
            {"id": 2, "message": "Progress"},
        ]
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps(comments), stderr=""
        )
        client = self._make_client()
        result = client.list_comments("bc-42")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["message"], "Started work")

    @patch("subprocess.run")
    def test_list_comments_empty(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr=""
        )
        client = self._make_client()
        result = client.list_comments("bc-42")
        self.assertEqual(result, [])

    @patch("subprocess.run")
    def test_list_comments_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error"
        )
        client = self._make_client()
        result = client.list_comments("bc-42")
        self.assertEqual(result, [])


class TestSyncPush(unittest.TestCase):
    """Test sync_push method."""

    def _make_client(self, sync_mode="direct"):
        cfg = BeadsServerConfig(sync_mode=sync_mode)
        return BeadsClient(cfg, beads_dir="/tmp/.beads")

    @patch("subprocess.run")
    def test_sync_push_direct(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        client = self._make_client("direct")
        result = client.sync_push()
        self.assertTrue(result)

        # Direct mode only does dolt commit, not push
        cmd = mock_run.call_args[0][0]
        self.assertIn("commit", cmd)

    @patch("subprocess.run")
    def test_sync_push_dolt(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        client = self._make_client("dolt")
        result = client.sync_push()
        self.assertTrue(result)

        # Dolt mode does commit + push (2 calls)
        self.assertEqual(mock_run.call_count, 2)

    def test_sync_push_unknown_mode(self):
        client = self._make_client("ftp")
        result = client.sync_push()
        self.assertFalse(result)


class TestSyncPull(unittest.TestCase):
    """Test sync_pull method."""

    def _make_client(self, sync_mode="direct"):
        cfg = BeadsServerConfig(sync_mode=sync_mode)
        return BeadsClient(cfg, beads_dir="/tmp/.beads")

    @patch("subprocess.run")
    def test_sync_pull_direct_is_noop(self, mock_run):
        client = self._make_client("direct")
        result = client.sync_pull()
        self.assertTrue(result)
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_sync_pull_dolt(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        client = self._make_client("dolt")
        result = client.sync_pull()
        self.assertTrue(result)

        cmd = mock_run.call_args[0][0]
        self.assertIn("pull", cmd)

    def test_sync_pull_unknown_mode(self):
        client = self._make_client("ftp")
        result = client.sync_pull()
        self.assertFalse(result)


class TestTestConnection(unittest.TestCase):
    """Test test_connection method."""

    def _make_client(self):
        return BeadsClient(BeadsServerConfig(), beads_dir="/tmp/.beads")

    @patch("subprocess.run")
    def test_connection_success(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr=""
        )
        client = self._make_client()
        self.assertTrue(client.test_connection())

    @patch("subprocess.run")
    def test_connection_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="connection refused"
        )
        client = self._make_client()
        self.assertFalse(client.test_connection())

    @patch("subprocess.run")
    def test_connection_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="bd", timeout=30)
        client = self._make_client()
        self.assertFalse(client.test_connection())


if __name__ == "__main__":
    unittest.main()
