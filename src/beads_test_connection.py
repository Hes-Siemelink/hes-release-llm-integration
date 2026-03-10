"""
beads_test_connection.py -- Test connection script for BeadsServer configuration.

Validates that the bd CLI can reach the beads server and access beads
by initializing metadata and running a basic bd command.
"""

from digitalai.release.integration import BaseTask

from src.beads_client import BeadsClient


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

        host = server.get('host', '(unset)')
        port = server.get('port', '(unset)')
        project = server.get('projectId', '(unset)')
        print(
            f"Testing beads server connection to {host}:{port} "
            f"(project: {project})..."
        )

        try:
            client = BeadsClient.from_server_properties(server)
            client.init_metadata()

            ok, detail = client.test_connection()
            if ok:
                self.set_output_property("commandResponse", {
                    "success": "true",
                    "output": (
                        f"Connected to beads server at {host}:{port} "
                        f"(project: {project})"
                    ),
                })
                print("Beads server connection successful")
            else:
                raise RuntimeError(
                    f"bd CLI could not connect to the beads server at "
                    f"{host}:{port}. {detail}"
                )

        except Exception as e:
            if isinstance(e, RuntimeError):
                raise
            raise RuntimeError(f"Beads connection test failed: {e}") from e
