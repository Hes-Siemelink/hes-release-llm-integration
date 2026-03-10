"""
Tests for beads_test_connection.py -- BeadsServer test connection script.

All subprocess calls are mocked; no real bd binary is needed.
"""

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from src.beads_test_connection import BeadsTestConnection


def _make_task(server_props):
    """Create a BeadsTestConnection task with given server properties."""
    task = BeadsTestConnection()
    task.input_properties = {"server": server_props}
    task._output_properties = {}

    def set_output(key, value):
        task._output_properties[key] = value

    task.set_output_property = set_output
    return task


class TestBeadsTestConnection(unittest.TestCase):
    """Test BeadsTestConnection task."""

    @patch("src.beads_test_connection.BeadsClient")
    def test_success(self, MockClient):
        mock_instance = MagicMock()
        mock_instance.test_connection.return_value = True
        MockClient.from_server_properties.return_value = mock_instance

        task = _make_task({
            "host": "beads-server",
            "port": 3306,
            "projectId": "proj-1",
            "prefix": "bc",
            "syncMode": "direct",
            "actor": "bot",
        })
        task.execute()

        self.assertEqual(task._output_properties["commandResponse"]["status"], "OK")
        self.assertEqual(task._output_properties["commandResponse"]["projectId"], "proj-1")

        mock_instance.init_metadata.assert_called_once()
        mock_instance.test_connection.assert_called_once()

    @patch("src.beads_test_connection.BeadsClient")
    def test_connection_failure(self, MockClient):
        mock_instance = MagicMock()
        mock_instance.test_connection.return_value = False
        MockClient.from_server_properties.return_value = mock_instance

        task = _make_task({
            "host": "bad-host",
            "port": 3306,
            "projectId": "proj-1",
        })
        with self.assertRaises(RuntimeError) as ctx:
            task.execute()
        self.assertIn("could not connect", str(ctx.exception))

    def test_missing_project_id(self):
        task = _make_task({
            "host": "beads-server",
            "port": 3306,
            "projectId": "",
        })
        with self.assertRaises(ValueError) as ctx:
            task.execute()
        self.assertIn("Project ID is required", str(ctx.exception))

    @patch("src.beads_test_connection.BeadsClient")
    def test_init_metadata_error(self, MockClient):
        mock_instance = MagicMock()
        mock_instance.init_metadata.side_effect = OSError("permission denied")
        MockClient.from_server_properties.return_value = mock_instance

        task = _make_task({
            "host": "beads-server",
            "port": 3306,
            "projectId": "proj-1",
        })
        with self.assertRaises(RuntimeError) as ctx:
            task.execute()
        self.assertIn("Beads connection test failed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
