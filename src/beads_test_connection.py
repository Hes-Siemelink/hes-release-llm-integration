"""
beads_test_connection.py -- Test connection script for BeadsServer configuration.

Validates that the bd CLI can reach the beads server and access beads
by initializing metadata and running a basic bd command.
"""

import logging

from digitalai.release.integration import BaseTask

from src.beads_client import BeadsClient

logger = logging.getLogger(__name__)


class BeadsTestConnection(BaseTask):
    """
    Test connection script for code-agent.BeadsServer configuration.

    Initializes the beads metadata from server config, then runs
    a test query to verify connectivity.
    """

    def execute(self) -> None:
        server = self.input_properties.get("server", {})

        if not server.get("projectId"):
            raise ValueError("Project ID is required")

        logger.info("Testing beads server connection...")

        try:
            client = BeadsClient.from_server_properties(server)
            client.init_metadata()

            if client.test_connection():
                self.set_output_property("commandResponse", {
                    "success": "true",
                    "output": (
                        f"Connected to beads server at "
                        f"{server.get('host', '')}:{server.get('port', '')} "
                        f"(project: {server.get('projectId', '')})"
                    ),
                })
                logger.info("Beads server connection successful")
            else:
                raise RuntimeError(
                    "bd CLI could not connect to the beads server. "
                    "Check host, port, and that the Dolt server is running."
                )

        except Exception as e:
            if isinstance(e, RuntimeError):
                raise
            raise RuntimeError(f"Beads connection test failed: {e}") from e
