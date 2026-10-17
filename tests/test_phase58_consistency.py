"""
Project Continuum — Phase 58 Test Suite
========================================
Milestone 37: Durable Storage and Migration
Phase 58: Consistency and Recovery

Validates:
1. Clean storage detection: audit reports clean state when all records are valid.
2. Malformed record detection & non-destructive quarantine: zero data loss (I-14).
3. Missing activity detection & safe reconstruction: preserves checkpoint history.
4. Orphaned checkpoint detection & activity harmonization.
5. Broken branch/parent reference detection & isolation into metadata.
6. Stale temporary file detection & cleanup from interrupted writes.
7. Derived-index mismatch detection & deterministic rebuild (I-06).
8. Repeat check idempotence: repair is repeatable and leaves storage 100% clean.
"""

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from core.activity import Activity, ActivityType
from core.checkpoint import UniversalCheckpoint
from storage.activity_store import ActivityCheckpointStore
from storage.consistency import (
    ConsistencyIssueType,
    StorageConsistencyEngine,
)


class TestPhase58Consistency(unittest.TestCase):
    """Test suite for consistency auditing, corruption recovery, and non-destructive repair."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="continuum_p58_test_")
        self.workspace_path = Path(self.temp_dir)
        self.continuum_dir = self.workspace_path / ".continuum"
        self.store = ActivityCheckpointStore(str(self.workspace_path))
        self.engine = StorageConsistencyEngine(str(self.workspace_path))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_audit_clean_storage(self):
        """Verifies that an uncorrupted storage reports 0 issues and is_clean=True."""
        act = self.store.create_activity(Activity.create_blank(title="Healthy Activity"))
        self.store.commit_checkpoint(UniversalCheckpoint.create_minimal(activity_id=act.id))

        report = self.engine.audit()
        self.assertTrue(report.is_clean)
        self.assertEqual(len(report.issues_found), 0)
        self.assertEqual(report.total_activities_found, 1)
        self.assertEqual(report.total_checkpoints_found, 1)

    def test_detect_and_quarantine_malformed_records(self):
        """Verifies that malformed JSON is detected, quarantined with a manifest, and not destroyed."""
        act = self.store.create_activity(Activity.create_blank(title="Corrupt Test"))
        chk_dir = self.store._get_checkpoints_dir(act.id)
        corrupt_file = chk_dir / "chk_broken_fixture.json"
        corrupt_file.write_text("{ unclosed bad json content !!", encoding="utf-8")

        # Audit
        report = self.engine.audit()
        self.assertFalse(report.is_clean)
        issue = next(i for i in report.issues_found if i.issue_type == ConsistencyIssueType.MALFORMED_RECORD)
        self.assertEqual(issue.entity_id, "chk_broken_fixture")

        # Repair
        repair_res = self.engine.repair()
        self.assertTrue(repair_res.is_clean_post_repair)
        self.assertEqual(len(repair_res.quarantined_files), 1)

        # Ensure quarantined file exists in .continuum/quarantine/
        quarantined_path = Path(repair_res.quarantined_files[0])
        self.assertTrue(quarantined_path.exists())
        self.assertIn("unclosed bad json", quarantined_path.read_text(encoding="utf-8"))

        # Ensure quarantine manifest exists
        manifest_path = quarantined_path.parent / f"{quarantined_path.name}.manifest.json"
        self.assertTrue(manifest_path.exists())

        # Ensure original directory is clean
        self.assertFalse(corrupt_file.exists())
        self.assertTrue(self.engine.audit().is_clean)

    def test_detect_and_reconstruct_missing_activity(self):
        """Verifies that missing activity.json is detected and reconstructed without losing checkpoints."""
        act = self.store.create_activity(Activity.create_blank(title="Activity to Disappear"))
        chk = self.store.commit_checkpoint(UniversalCheckpoint.create_minimal(activity_id=act.id))

        # Delete activity.json while keeping directory and checkpoints
        act_file = self.store._get_activity_file(act.id)
        act_file.unlink()

        # Audit
        report = self.engine.audit()
        self.assertFalse(report.is_clean)
        self.assertTrue(any(i.issue_type == ConsistencyIssueType.MISSING_ACTIVITY_RECORD for i in report.issues_found))

        # Repair
        repair_res = self.engine.repair()
        self.assertTrue(repair_res.is_clean_post_repair)

        # Check activity was reconstructed
        reconstructed = self.store.get_activity(act.id)
        self.assertEqual(reconstructed.id, act.id)
        self.assertIn("Recovered", reconstructed.title)

        # Check checkpoint is still present and valid
        loaded_chk = self.store.get_checkpoint(chk.id, act.id)
        self.assertEqual(loaded_chk.id, chk.id)

    def test_detect_and_harmonize_orphaned_checkpoints(self):
        """Verifies that orphaned checkpoints with mismatched activity_id are detected and harmonized."""
        act = self.store.create_activity(Activity.create_blank(title="Folder Activity"))
        chk_dir = self.store._get_checkpoints_dir(act.id)

        # Create checkpoint file that claims a different activity_id
        orphan_data = {
            "id": "chk_misplaced_01",
            "activity_id": "act_some_other_folder",
            "timestamp": "2026-10-16T12:00:00Z",
            "completed_work": ["Misplaced item"],
        }
        (chk_dir / "chk_misplaced_01.json").write_text(json.dumps(orphan_data), encoding="utf-8")

        # Audit
        report = self.engine.audit()
        self.assertFalse(report.is_clean)
        self.assertTrue(any(i.issue_type == ConsistencyIssueType.ORPHANED_CHECKPOINT for i in report.issues_found))

        # Repair
        repair_res = self.engine.repair()
        self.assertTrue(repair_res.is_clean_post_repair)

        # Verify activity_id harmonized
        harmonized_chk = self.store.get_checkpoint("chk_misplaced_01", act.id)
        self.assertEqual(harmonized_chk.activity_id, act.id)

    def test_detect_and_isolate_invalid_branch_references(self):
        """Verifies that invalid branch/parent references are isolated into metadata without deleting data."""
        act = self.store.create_activity(Activity.create_blank(title="Branch Check"))
        chk_dir = self.store._get_checkpoints_dir(act.id)

        # Checkpoint with ghost parent and ghost branch source
        broken_chk_data = {
            "id": "chk_broken_parent_01",
            "activity_id": act.id,
            "timestamp": "2026-10-16T12:00:00Z",
            "parent_checkpoint_id": "chk_ghost_parent_999",
            "branch_source_checkpoint_id": "chk_ghost_source_888",
            "completed_work": ["Orphan branch work"],
        }
        (chk_dir / "chk_broken_parent_01.json").write_text(json.dumps(broken_chk_data), encoding="utf-8")

        # Audit
        report = self.engine.audit()
        self.assertFalse(report.is_clean)
        branch_issues = [i for i in report.issues_found if i.issue_type == ConsistencyIssueType.INVALID_BRANCH_REFERENCE]
        self.assertTrue(len(branch_issues) >= 1)

        # Repair
        repair_res = self.engine.repair()
        self.assertTrue(repair_res.is_clean_post_repair)

        # Verify reference was safely isolated in metadata and nulled
        repaired_chk = self.store.get_checkpoint("chk_broken_parent_01", act.id)
        self.assertIsNone(repaired_chk.parent_checkpoint_id)
        self.assertIsNone(repaired_chk.branch_source_checkpoint_id)
        self.assertEqual(repaired_chk.metadata.get("unresolved_parent_id"), "chk_ghost_parent_999")
        self.assertEqual(repaired_chk.metadata.get("unresolved_branch_source_id"), "chk_ghost_source_888")

    def test_detect_and_cleanup_stale_temporary_files(self):
        """Verifies that abandoned temporary files from interrupted operations are detected and cleaned."""
        act = self.store.create_activity(Activity.create_blank(title="Tmp Test"))
        act_dir = self.store._get_activity_dir(act.id)
        chk_dir = self.store._get_checkpoints_dir(act.id)

        stale_tmp1 = act_dir / "activity.json.tmp_9999"
        stale_tmp2 = chk_dir / "chk_abc.json.tmp_8888"
        stale_tmp1.write_text("in flight activity", encoding="utf-8")
        stale_tmp2.write_text("in flight checkpoint", encoding="utf-8")

        # Audit
        report = self.engine.audit()
        self.assertFalse(report.is_clean)
        tmp_issues = [i for i in report.issues_found if i.issue_type == ConsistencyIssueType.STALE_TEMPORARY_FILE]
        self.assertEqual(len(tmp_issues), 2)

        # Repair
        repair_res = self.engine.repair()
        self.assertTrue(repair_res.is_clean_post_repair)
        self.assertFalse(stale_tmp1.exists())
        self.assertFalse(stale_tmp2.exists())

    def test_detect_and_rebuild_derived_index_mismatch(self):
        """Verifies that index desynchronization is detected and rebuilt from authoritative JSON (I-06)."""
        act1 = self.store.create_activity(Activity.create_blank(title="Index Desync Test"))
        chk1 = self.store.commit_checkpoint(UniversalCheckpoint.create_minimal(activity_id=act1.id))

        # Simulate index desynchronization by deleting rows directly from SQLite
        with self.store._get_db_connection() as conn:
            conn.execute("DELETE FROM checkpoints_idx")

        # Audit
        report = self.engine.audit()
        self.assertFalse(report.is_clean)
        self.assertTrue(any(i.issue_type == ConsistencyIssueType.DERIVED_INDEX_MISMATCH for i in report.issues_found))

        # Repair
        repair_res = self.engine.repair()
        self.assertTrue(repair_res.is_clean_post_repair)
        self.assertTrue(repair_res.rebuilt_index_records >= 2)

        # Verify index matches authoritative files
        post_audit = self.engine.audit()
        self.assertTrue(post_audit.is_clean)

    def test_repeat_check_idempotence(self):
        """Verifies that repair is completely repeatable and running audit/repair again reports 0 issues."""
        act = self.store.create_activity(Activity.create_blank(title="Idempotence Activity"))
        act_dir = self.store._get_activity_dir(act.id)
        (act_dir / "stale.tmp_123").write_text("junk", encoding="utf-8")

        # First repair
        res1 = self.engine.repair()
        self.assertTrue(res1.is_clean_post_repair)

        # Second audit
        audit2 = self.engine.audit()
        self.assertTrue(audit2.is_clean)
        self.assertEqual(len(audit2.issues_found), 0)

        # Second repair
        res2 = self.engine.repair()
        self.assertTrue(res2.is_clean_post_repair)
        self.assertEqual(res2.issues_detected, 0)
        self.assertEqual(res2.issues_repaired, 0)


if __name__ == "__main__":
    unittest.main()
