"""
Tests for agents_md.py -- AGENTS.md template injection.
"""

import os
import shutil
import tempfile
import unittest
import unittest.mock

from src.agents_md import (
    BACKUP_SUFFIX,
    SEPARATOR,
    cleanup_agents_md,
    cleanup_opencode_config,
    inject_agents_md,
    inject_opencode_config,
)


class TestInjectAgentsMd(unittest.TestCase):
    """Test inject_agents_md function."""

    def setUp(self):
        self.workspace = tempfile.mkdtemp()
        # Use the actual resources directory in this repo
        self.template_dir = os.path.join(
            os.path.dirname(__file__), "..", "resources"
        )

    def tearDown(self):
        shutil.rmtree(self.workspace)

    def test_inject_into_empty_workspace(self):
        """Creates AGENTS.md when none exists."""
        path = inject_agents_md(self.workspace, "bc-42", self.template_dir)

        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            content = f.read()
        self.assertIn("bc-42", content)
        self.assertNotIn("${BEAD_ID}", content)

        # No backup should exist
        self.assertFalse(os.path.isfile(path + BACKUP_SUFFIX))

    def test_inject_with_existing_agents_md(self):
        """Appends to existing AGENTS.md and creates backup."""
        original_content = "# Project AGENTS.md\n\nOriginal content here.\n"
        agents_path = os.path.join(self.workspace, "AGENTS.md")
        with open(agents_path, "w") as f:
            f.write(original_content)

        path = inject_agents_md(self.workspace, "bc-99", self.template_dir)

        # Backup should exist with original content
        backup_path = path + BACKUP_SUFFIX
        self.assertTrue(os.path.isfile(backup_path))
        with open(backup_path) as f:
            self.assertEqual(f.read(), original_content)

        # Main file should have both original and injected content
        with open(path) as f:
            content = f.read()
        self.assertIn("Original content here.", content)
        self.assertIn("bc-99", content)
        self.assertIn("Orchestrator Instructions", content)

    def test_bead_id_substitution(self):
        """All ${BEAD_ID} placeholders are replaced."""
        inject_agents_md(self.workspace, "proj-123", self.template_dir)

        with open(os.path.join(self.workspace, "AGENTS.md")) as f:
            content = f.read()

        self.assertNotIn("${BEAD_ID}", content)
        # The template references BEAD_ID in multiple places
        self.assertGreater(content.count("proj-123"), 1)

    @unittest.mock.patch("src.agents_md.DEFAULT_TEMPLATE_DIR", "/also-nonexistent")
    def test_template_not_found(self):
        """Raises FileNotFoundError when template is missing."""
        with self.assertRaises(FileNotFoundError):
            inject_agents_md(self.workspace, "bc-42", template_dir="/nonexistent")


class TestCleanupAgentsMd(unittest.TestCase):
    """Test cleanup_agents_md function."""

    def setUp(self):
        self.workspace = tempfile.mkdtemp()
        self.template_dir = os.path.join(
            os.path.dirname(__file__), "..", "resources"
        )

    def tearDown(self):
        shutil.rmtree(self.workspace)

    def test_cleanup_restores_backup(self):
        """Restores original AGENTS.md from backup."""
        original_content = "# Original\n"
        agents_path = os.path.join(self.workspace, "AGENTS.md")

        # Simulate inject: create backup and modified file
        with open(agents_path + BACKUP_SUFFIX, "w") as f:
            f.write(original_content)
        with open(agents_path, "w") as f:
            f.write(original_content + SEPARATOR + "injected stuff")

        cleanup_agents_md(self.workspace)

        # Original should be restored
        with open(agents_path) as f:
            self.assertEqual(f.read(), original_content)
        # Backup should be gone
        self.assertFalse(os.path.isfile(agents_path + BACKUP_SUFFIX))

    def test_cleanup_removes_created_file(self):
        """Removes AGENTS.md when it was created from scratch (no backup)."""
        agents_path = os.path.join(self.workspace, "AGENTS.md")
        with open(agents_path, "w") as f:
            f.write("injected content only")

        cleanup_agents_md(self.workspace)

        self.assertFalse(os.path.isfile(agents_path))

    def test_cleanup_noop_when_no_file(self):
        """Does nothing when there's no AGENTS.md at all."""
        # Should not raise
        cleanup_agents_md(self.workspace)

    def test_full_roundtrip(self):
        """Inject then cleanup restores original state."""
        original_content = "# My Project\n\nCustom instructions.\n"
        agents_path = os.path.join(self.workspace, "AGENTS.md")
        with open(agents_path, "w") as f:
            f.write(original_content)

        # Inject
        inject_agents_md(self.workspace, "bc-1", self.template_dir)

        # Verify injection happened
        with open(agents_path) as f:
            self.assertIn("bc-1", f.read())

        # Cleanup
        cleanup_agents_md(self.workspace)

        # Verify restoration
        with open(agents_path) as f:
            self.assertEqual(f.read(), original_content)


class TestInjectOpencodeConfig(unittest.TestCase):
    """Test inject_opencode_config function."""

    def setUp(self):
        self.workspace = tempfile.mkdtemp()
        self.template_dir = os.path.join(
            os.path.dirname(__file__), "..", "resources"
        )

    def tearDown(self):
        shutil.rmtree(self.workspace)

    def test_copies_config(self):
        """Writes container-opencode.json to workspace as valid JSON."""
        path = inject_opencode_config(self.workspace, self.template_dir)

        self.assertTrue(os.path.isfile(path))
        self.assertTrue(path.endswith("opencode.json"))

        import json
        with open(path) as f:
            data = json.load(f)
        self.assertIn("permission", data)

    def test_no_llm_server_writes_unmodified_config(self):
        """Without llm_server, config is written without URL changes."""
        import json
        path = inject_opencode_config(self.workspace, self.template_dir)

        with open(path) as f:
            data = json.load(f)

        # docker-model-runner provider should still have original baseURL
        dmr = data.get("provider", {}).get("docker-model-runner", {})
        if dmr:
            base_url = dmr.get("options", {}).get("baseURL", "")
            # Should be whatever was in the template, not overridden
            self.assertNotEqual(base_url, "http://custom-host:8080")

    def test_docker_model_runner_url_injected(self):
        """URL from llm_server is injected into docker-model-runner baseURL."""
        import json
        llm_server = {
            "provider": "docker-model-runner",
            "url": "http://custom-host:8080",
        }
        path = inject_opencode_config(
            self.workspace, self.template_dir, llm_server=llm_server
        )

        with open(path) as f:
            data = json.load(f)

        dmr = data["provider"]["docker-model-runner"]
        self.assertEqual(dmr["options"]["baseURL"], "http://custom-host:8080")

    def test_non_docker_provider_url_ignored(self):
        """URL is not applied when provider is not docker-model-runner."""
        import json
        llm_server = {
            "provider": "anthropic",
            "url": "http://custom-host:8080",
            "apiKey": "sk-test",
        }
        path = inject_opencode_config(
            self.workspace, self.template_dir, llm_server=llm_server
        )

        with open(path) as f:
            data = json.load(f)

        # anthropic provider should not have baseURL set to custom URL
        anthropic = data.get("provider", {}).get("anthropic", {})
        base_url = anthropic.get("options", {}).get("baseURL", "")
        self.assertNotEqual(base_url, "http://custom-host:8080")

    def test_empty_url_not_applied(self):
        """Empty URL string does not modify the config."""
        import json
        llm_server = {
            "provider": "docker-model-runner",
            "url": "",
        }
        path = inject_opencode_config(
            self.workspace, self.template_dir, llm_server=llm_server
        )

        # Read template for comparison
        template_path = os.path.join(self.template_dir, "container-opencode.json")
        with open(template_path) as f:
            original = json.load(f)
        with open(path) as f:
            written = json.load(f)

        # docker-model-runner config should be unchanged
        orig_dmr = original.get("provider", {}).get("docker-model-runner", {})
        written_dmr = written.get("provider", {}).get("docker-model-runner", {})
        self.assertEqual(
            orig_dmr.get("options", {}).get("baseURL"),
            written_dmr.get("options", {}).get("baseURL"),
        )

    def test_backs_up_existing_opencode_json(self):
        """Backs up existing opencode.json before overwriting."""
        import json
        original_config = {"$schema": "test", "mcp": {"my-server": {"url": "http://localhost:8080"}}}
        config_path = os.path.join(self.workspace, "opencode.json")
        with open(config_path, "w") as f:
            json.dump(original_config, f)

        inject_opencode_config(self.workspace, self.template_dir)

        # Backup should exist with original content
        backup_path = config_path + BACKUP_SUFFIX
        self.assertTrue(os.path.isfile(backup_path))
        with open(backup_path) as f:
            backup_data = json.load(f)
        self.assertEqual(backup_data, original_config)

    def test_no_backup_when_no_existing_config(self):
        """No backup created when workspace has no opencode.json."""
        inject_opencode_config(self.workspace, self.template_dir)

        backup_path = os.path.join(self.workspace, "opencode.json" + BACKUP_SUFFIX)
        self.assertFalse(os.path.isfile(backup_path))

    @unittest.mock.patch("src.agents_md.DEFAULT_TEMPLATE_DIR", "/also-nonexistent")
    def test_config_not_found(self):
        """Raises FileNotFoundError when config is missing."""
        with self.assertRaises(FileNotFoundError):
            inject_opencode_config(self.workspace, template_dir="/nonexistent")


class TestCleanupOpencodeConfig(unittest.TestCase):
    """Test cleanup_opencode_config function."""

    def setUp(self):
        self.workspace = tempfile.mkdtemp()
        self.template_dir = os.path.join(
            os.path.dirname(__file__), "..", "resources"
        )

    def tearDown(self):
        shutil.rmtree(self.workspace)

    def test_cleanup_restores_backup(self):
        """Restores original opencode.json from backup."""
        import json
        original_config = {"$schema": "test", "mcp": {"my-server": {"url": "http://localhost"}}}
        config_path = os.path.join(self.workspace, "opencode.json")
        backup_path = config_path + BACKUP_SUFFIX

        with open(backup_path, "w") as f:
            json.dump(original_config, f)
        with open(config_path, "w") as f:
            json.dump({"injected": True}, f)

        cleanup_opencode_config(self.workspace)

        with open(config_path) as f:
            restored = json.load(f)
        self.assertEqual(restored, original_config)
        self.assertFalse(os.path.isfile(backup_path))

    def test_cleanup_removes_created_file(self):
        """Removes opencode.json when it was created from scratch (no backup)."""
        config_path = os.path.join(self.workspace, "opencode.json")
        with open(config_path, "w") as f:
            f.write('{"injected": true}')

        cleanup_opencode_config(self.workspace)

        self.assertFalse(os.path.isfile(config_path))

    def test_cleanup_noop_when_no_file(self):
        """Does nothing when there's no opencode.json at all."""
        cleanup_opencode_config(self.workspace)

    def test_full_roundtrip(self):
        """Inject then cleanup restores original opencode.json."""
        import json
        original_config = {"$schema": "test", "mcp": {"goals-app": {"url": "http://localhost:8080"}}}
        config_path = os.path.join(self.workspace, "opencode.json")
        with open(config_path, "w") as f:
            json.dump(original_config, f)

        # Inject
        inject_opencode_config(self.workspace, self.template_dir)

        # Verify injection overwrote the file
        with open(config_path) as f:
            injected = json.load(f)
        self.assertNotEqual(injected, original_config)

        # Cleanup
        cleanup_opencode_config(self.workspace)

        # Verify restoration
        with open(config_path) as f:
            restored = json.load(f)
        self.assertEqual(restored, original_config)


if __name__ == "__main__":
    unittest.main()
