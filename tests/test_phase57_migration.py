"""
Project Continuum — Phase 57 Test Suite
========================================
Milestone 37: Durable Storage and Migration
Phase 57: Versioned, Idempotent Migration

Validates:
1. Fresh install handling: initializes directly to v1.4.0 schema.
2. Upgrade from legacy v1.0.0-v1.3.0 workspaces: maps state.json, history, and handoffs.
3. Dry-run preview: accurately counts activities, checkpoints, and skipped records.
4. Repeated migration idempotence: safe re-runs with zero record duplication (I-14).
5. Malformed input resilience: corrupted files are safely recorded in skipped_records.
6. Unsupported schema versions rejected cleanly with MigrationError.
7. Verified recovery & rollback: pre-migration backup preserves original data.
8. Interrupted migration retry safety: safe completion after partial or aborted runs.
"""

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from core.activity import Activity
from core.invariants import MigrationError
from storage.activity_store import ActivityCheckpointStore
from storage.migration import (
    ContinuumMigrator,
    MigrationResult,
    CURRENT_SCHEMA_VERSION,
)


class TestPhase57Migration(unittest.TestCase):
    """Test suite for versioned, idempotent schema migration."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="continuum_p57_test_")
        self.workspace_path = Path(self.temp_dir)
        self.continuum_dir = self.workspace_path / ".continuum"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_fresh_install_migration(self):
        """Verifies that an empty workspace is recognized as fresh install and initialized to v1.4.0."""
        migrator = ContinuumMigrator(str(self.workspace_path))
        self.assertEqual(migrator.detect_version(), "fresh_install")

        # Dry run preview
        plan = migrator.plan_migration()
        self.assertTrue(plan.success)
        self.assertTrue(plan.is_dry_run)
        self.assertEqual(plan.target_version, CURRENT_SCHEMA_VERSION)

        # Execute migration
        result = migrator.migrate()
        self.assertTrue(result.success)
        self.assertFalse(result.is_dry_run)
        self.assertEqual(migrator.detect_version(), CURRENT_SCHEMA_VERSION)
        self.assertTrue((self.continuum_dir / "migration.json").exists())

    def test_upgrade_from_v1_0_0_legacy_workspace(self):
        """Verifies upgrading from a legacy v1.0.0 workspace with state.json, history, and handoffs."""
        # 1. Setup legacy v1.0.0 structure
        self.continuum_dir.mkdir(parents=True, exist_ok=True)
        history_dir = self.continuum_dir / "history"
        handoffs_dir = self.continuum_dir / "handoffs"
        history_dir.mkdir(parents=True, exist_ok=True)
        handoffs_dir.mkdir(parents=True, exist_ok=True)

        # Legacy active state
        legacy_state = {
            "schema_version": "1.0.0",
            "project_id": "proj_legacy_alpha",
            "created_at": "2026-10-15T10:00:00Z",
            "updated_at": "2026-10-15T12:00:00Z",
            "project_state": {"files": ["main.py", "utils.py"]},
            "conversational_state": {"session_id": "sess_01"},
            "agent_execution_state": {"agent_id": "agent_alpha"},
            "evidence_pool": {},
            "graph_nodes": {},
            "graph_edges": [],
            "contradictions": [],
        }
        (self.continuum_dir / "state.json").write_text(json.dumps(legacy_state), encoding="utf-8")

        # Legacy history snapshot
        legacy_history = dict(legacy_state)
        legacy_history["updated_at"] = "2026-10-15T11:00:00Z"
        (history_dir / "state_20261015_110000_initial.json").write_text(
            json.dumps(legacy_history), encoding="utf-8"
        )

        # Legacy handoff checkpoint
        legacy_handoff = {
            "checkpoint_id": "chk_handoff_legacy_01",
            "timestamp": "2026-10-15T11:30:00Z",
            "origin_model": "claude",
            "target_model": "gpt",
            "prompt_summary": "Refactored payment gateway",
            "total_messages": 12,
            "total_code_blocks": 4,
        }
        (handoffs_dir / "checkpoint_chk_handoff_legacy_01.json").write_text(
            json.dumps(legacy_handoff), encoding="utf-8"
        )

        migrator = ContinuumMigrator(str(self.workspace_path))
        self.assertEqual(migrator.detect_version(), "1.0.0")

        # 2. Dry run preview
        plan = migrator.plan_migration()
        self.assertTrue(plan.success)
        self.assertEqual(plan.activities_migrated, 1)
        self.assertEqual(plan.checkpoints_migrated, 3)  # active state + 1 history + 1 handoff

        # 3. Execute migration with backup
        res = migrator.migrate(create_backup=True)
        self.assertTrue(res.success)
        self.assertIsNotNone(res.backup_path)
        self.assertTrue(Path(res.backup_path).exists())
        self.assertEqual(migrator.detect_version(), CURRENT_SCHEMA_VERSION)

        # 4. Verify migrated entities via ActivityCheckpointStore
        store = ActivityCheckpointStore(str(self.workspace_path))
        act = store.get_activity("act_migrated_workspace")
        self.assertIsNotNone(act)
        self.assertEqual(act.id, "act_migrated_workspace")
        self.assertIn("v1.0.0", act.tags)

        # Checkpoints check
        chks, total = store.list_checkpoints(act.id)
        self.assertEqual(total, 3)
        self.assertEqual(len(chks), 3)

    def test_repeated_migration_idempotence(self):
        """Verifies that running migration repeatedly is strictly idempotent with zero data duplication (I-14)."""
        # Setup legacy workspace
        self.continuum_dir.mkdir(parents=True, exist_ok=True)
        (self.continuum_dir / "state.json").write_text(
            json.dumps({"schema_version": "1.0.0", "project_id": "proj_repeat"}),
            encoding="utf-8",
        )

        migrator = ContinuumMigrator(str(self.workspace_path))
        res1 = migrator.migrate()
        self.assertTrue(res1.success)

        store = ActivityCheckpointStore(str(self.workspace_path))
        _, count1 = store.list_checkpoints("act_migrated_workspace")

        # Second run
        res2 = migrator.migrate()
        self.assertTrue(res2.success)
        self.assertIn("idempotent", res2.details.lower())

        # Third run
        res3 = migrator.migrate()
        self.assertTrue(res3.success)

        _, count3 = store.list_checkpoints("act_migrated_workspace")
        self.assertEqual(count1, count3)

    def test_malformed_input_handling_and_skipped_reporting(self):
        """Verifies that malformed or corrupt legacy files are isolated, skipped, and reported cleanly."""
        self.continuum_dir.mkdir(parents=True, exist_ok=True)
        handoffs_dir = self.continuum_dir / "handoffs"
        handoffs_dir.mkdir(parents=True, exist_ok=True)

        (self.continuum_dir / "state.json").write_text(
            json.dumps({"schema_version": "1.0.0", "project_id": "proj_corrupt_test"}),
            encoding="utf-8",
        )

        # 1 valid handoff, 1 corrupt handoff
        valid_handoff = {
            "checkpoint_id": "chk_valid_01",
            "prompt_summary": "Good checkpoint",
        }
        (handoffs_dir / "valid.json").write_text(json.dumps(valid_handoff), encoding="utf-8")
        (handoffs_dir / "corrupted.json").write_text("{ incomplete broken json ...", encoding="utf-8")

        migrator = ContinuumMigrator(str(self.workspace_path))
        res = migrator.migrate()

        self.assertTrue(res.success)
        # Should have 1 skipped record for corrupted.json
        self.assertEqual(len(res.records_skipped), 1)
        self.assertEqual(res.records_skipped[0].status, "skipped")
        self.assertIn("corrupted.json", res.records_skipped[0].source_path)

        # Valid records should have migrated successfully
        store = ActivityCheckpointStore(str(self.workspace_path))
        loaded_chk = store.get_checkpoint("chk_valid_01", "act_migrated_workspace")
        self.assertIsNotNone(loaded_chk)

    def test_unsupported_version_rejection(self):
        """Verifies that attempting to migrate an unknown/unsupported schema version raises MigrationError."""
        self.continuum_dir.mkdir(parents=True, exist_ok=True)
        (self.continuum_dir / "state.json").write_text(
            json.dumps({"schema_version": "99.0.0", "project_id": "proj_future"}),
            encoding="utf-8",
        )

        migrator = ContinuumMigrator(str(self.workspace_path))
        self.assertEqual(migrator.detect_version(), "unsupported")

        with self.assertRaises(MigrationError) as ctx:
            migrator.migrate()
        self.assertIn("Unsupported source schema version", str(ctx.exception))

    def test_recovery_and_rollback_on_failure(self):
        """Verifies that rollback restores the workspace to the exact pre-migration state."""
        self.continuum_dir.mkdir(parents=True, exist_ok=True)
        state_file = self.continuum_dir / "state.json"
        state_file.write_text(
            json.dumps({"schema_version": "1.0.0", "original_payload": "critical_data_123"}),
            encoding="utf-8",
        )

        migrator = ContinuumMigrator(str(self.workspace_path))
        backup_path = migrator.create_pre_migration_backup()
        self.assertTrue(backup_path.exists())

        # Modify state file to simulate corruption / destructive migration
        state_file.write_text("damaged data", encoding="utf-8")

        # Rollback
        restored = migrator.rollback(str(backup_path))
        self.assertTrue(restored)

        # Verify original content restored
        restored_data = json.loads(state_file.read_text(encoding="utf-8"))
        self.assertEqual(restored_data["original_payload"], "critical_data_123")

    def test_interrupted_migration_safe_retry(self):
        """Verifies that if a migration is aborted mid-way, running it again cleanly resumes."""
        self.continuum_dir.mkdir(parents=True, exist_ok=True)
        (self.continuum_dir / "state.json").write_text(
            json.dumps({"schema_version": "1.0.0", "project_id": "proj_resume"}),
            encoding="utf-8",
        )

        migrator = ContinuumMigrator(str(self.workspace_path))
        # Pre-create the root activity to simulate partial migration
        store = ActivityCheckpointStore(str(self.workspace_path))
        store.create_activity(
            Activity.create_blank(
                title="Migrated Workspace Activity",
                custom_id="act_migrated_workspace",
            )
        )

        # Now run migration; it should recognize the existing activity and proceed with checkpoints
        res = migrator.migrate()
        self.assertTrue(res.success)
        self.assertEqual(migrator.detect_version(), CURRENT_SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
