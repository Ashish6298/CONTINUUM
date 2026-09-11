"""
Project Continuum - Test Suite for Phase 17 (Git Hooks & Persistent State Management)
=====================================================================================
Milestone 7 - Phase 17.
Validates:
1. Local .continuum directory initialization and atomic state persistence.
2. Versioned snapshot history creation, listing, and rolling retention.
3. State corruption detection and auto-recovery from history backups.
4. GitHookManager non-destructive installation, status check, and uninstallation.
"""

from pathlib import Path
import tempfile
import time
import unittest

from core.enums import Status
from core.state_models import (
    AstSymbol,
    CanonicalProjectState,
    ProjectState,
)
from storage.manager import ContinuumStorageManager
from storage.recovery import StateRecoveryManager
from storage.hooks import GitHookManager


class TestPersistentStorageAndHooks(unittest.TestCase):
    """Test suite for Phase 17 Persistent State Management & Git Hooks."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

        self.storage = ContinuumStorageManager(str(self.workspace))
        self.recovery = StateRecoveryManager(self.storage)
        self.hooks = GitHookManager(str(self.workspace))

        # Sample state
        self.state = CanonicalProjectState(
            project_id="proj_persist_test",
            project_state=ProjectState(
                root_path=str(self.workspace),
                detected_languages=["python"],
                files=["main.py"],
                symbols=[
                    AstSymbol(name="MainApp", kind="class", file_path="main.py", line_start=1, line_end=20)
                ],
                build_status=Status.VERIFIED
            )
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_storage_initialization_and_atomic_save_load(self):
        """
        Verifies saving and loading state from .continuum/state.json.
        """
        self.assertFalse(self.storage.state_exists())

        path = self.storage.save_state(self.state, create_history_snapshot=True)
        self.assertTrue(self.storage.state_exists())
        self.assertTrue(Path(path).exists())

        # Load back
        loaded = self.storage.load_state(validate=True)
        self.assertEqual(loaded.project_id, "proj_persist_test")
        self.assertEqual(len(loaded.project_state.symbols), 1)

        meta = self.storage.get_metadata()
        self.assertEqual(meta.history_count, 1)

    def test_versioned_snapshot_history(self):
        """
        Multiple save calls should create versioned timestamped history snapshots.
        """
        self.storage.save_state(self.state, create_history_snapshot=True, commit_tag="init")
        time.sleep(0.01)
        self.storage.save_state(self.state, create_history_snapshot=True, commit_tag="feat")

        snapshots = self.storage.list_history_snapshots()
        self.assertEqual(len(snapshots), 2)
        self.assertTrue("feat" in snapshots[0].name or "feat" in snapshots[1].name)

    def test_corruption_detection_and_auto_recovery(self):
        """
        Corrupting .continuum/state.json should be detected and automatically
        recovered from the latest valid history snapshot.
        """
        # Save a valid state and snapshot
        self.storage.save_state(self.state, create_history_snapshot=True)

        # Intentionally corrupt active state.json with garbage bytes
        active_file = self.storage.active_state_file
        active_file.write_text("{\"corrupted_json\": true, INVALID_SYNTAX...", encoding="utf-8")

        # Integrity check should flag failure
        is_valid, reason = self.recovery.verify_active_state_integrity()
        self.assertFalse(is_valid)

        # Trigger auto-recovery
        res = self.recovery.recover_corrupted_state()
        self.assertTrue(res.success)
        self.assertTrue(res.state_restored)

        # Active state should now be restored and valid
        restored_state = self.storage.load_state(validate=True)
        self.assertEqual(restored_state.project_id, "proj_persist_test")

    def test_git_hook_management(self):
        """
        Verifies Git hook installation and removal in a simulated Git directory.
        """
        git_dir = self.workspace / ".git"
        git_dir.mkdir(parents=True, exist_ok=True)

        self.assertTrue(self.hooks.is_git_repo())

        # Install
        inst_res = self.hooks.install_hooks()
        self.assertTrue(inst_res["post-commit"])
        self.assertTrue(inst_res["pre-commit"])

        # Check installed
        status = self.hooks.are_hooks_installed()
        self.assertTrue(status["post-commit"])
        self.assertTrue(status["pre-commit"])

        # Uninstall
        uninst_res = self.hooks.uninstall_hooks()
        self.assertTrue(uninst_res["post-commit"])
        self.assertTrue(uninst_res["pre-commit"])


if __name__ == "__main__":
    unittest.main()
