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
        """Copies container-opencode.json to workspace."""
        path = inject_opencode_config(self.workspace, self.template_dir)

        self.assertTrue(os.path.isfile(path))
        self.assertTrue(path.endswith("opencode.json"))

        with open(path) as f:
            content = f.read()
        self.assertIn("permission", content)
        self.assertIn("allow", content)

    @unittest.mock.patch("src.agents_md.DEFAULT_TEMPLATE_DIR", "/also-nonexistent")
    def test_config_not_found(self):
        """Raises FileNotFoundError when config is missing."""
        with self.assertRaises(FileNotFoundError):
            inject_opencode_config(self.workspace, template_dir="/nonexistent")


if __name__ == "__main__":
    unittest.main()
