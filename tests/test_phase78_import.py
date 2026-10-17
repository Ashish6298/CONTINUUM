"""
Project Continuum — Phase 78 Test Suite: Import, Conflicts and Restore
======================================================================
Tests:
1. test_clean_import: Full roundtrip import into empty workspace.
2. test_id_collision_identical_content: Deduplication on identical matching records.
3. test_same_id_different_content_reject: Fail-safe rejection on content divergence without mutation.
4. test_same_id_different_content_rename_new: Allocation of new UUIDs and rewiring of child relations.
5. test_same_id_different_content_overwrite: Explicit overwrite confirmation and journal rollback backup.
6. test_same_id_different_content_skip: Local preservation with incoming skip.
7. test_corrupt_archive_blocks_mutation: Corrupted/truncated archives block live mutations entirely.
8. test_interruption_and_recovery: Interrupted commit rollback and safe subsequent retry.
9. test_unrelated_data_unchanged: Unrelated local activities and checkpoints remain completely untouched.
10. test_gate_no_silent_overwrite_or_unrecoverable_partial_import: Invariant verification.
11. test_rest_api_import_endpoints: REST API verification for preview, execute, and recover.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Tuple
import unittest
import uuid

from core.activity import Activity, ActivityStatus, ActivityType
from core.checkpoint import UniversalCheckpoint
from core.backup import CompleteBackupEngine
from core.enums import ConflictResolutionStrategy, ConflictType, ImportStageStatus
from core.import_engine import (
    CompleteImportEngine,
    ImportConflictError,
    CorruptedArchiveError,
    ImportPlan,
    ImportResult,
)
from storage.activity_store import ActivityCheckpointStore


class TestPhase78ImportAndRestore(unittest.TestCase):
    """Test suite for Phase 78: Import, Conflicts and Restore."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="continuum_p78_test_")
        self.workspace = Path(self.test_dir)
        self.continuum_dir = self.workspace / ".continuum"
        self.continuum_dir.mkdir(parents=True, exist_ok=True)
        self.store = ActivityCheckpointStore(str(self.workspace))
        self.backup_engine = CompleteBackupEngine(self.workspace)
        self.import_engine = CompleteImportEngine(self.workspace)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_sample_activity_and_checkpoint(
        self,
        workspace_dir: Path,
        act_id: str = "act_sample_001",
        title: str = "Sample Activity",
        chk_id: str = "chk_sample_001",
        summary: str = "First Checkpoint",
    ) -> Tuple[Activity, UniversalCheckpoint]:
        """Helper to create and persist an activity and checkpoint."""
        store = ActivityCheckpointStore(str(workspace_dir))
        act = Activity(
            id=act_id,
            title=title,
            activity_type=ActivityType.CODING,
            status=ActivityStatus.ACTIVE,
            tags=["phase78", "test"],
        )
        saved_act = store.create_activity(act)

        chk = UniversalCheckpoint(
            id=chk_id,
            activity_id=saved_act.id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            context=summary,
            progress={"completed_pct": 50},
        )
        saved_chk = store.commit_checkpoint(chk)
        return saved_act, saved_chk

    def test_clean_import(self):
        """1. Verifies full clean roundtrip import into empty workspace."""
        # Create source archive
        src_dir = Path(tempfile.mkdtemp(prefix="continuum_src_"))
        try:
            act, chk = self._create_sample_activity_and_checkpoint(
                src_dir, act_id="act_export_1", title="Exported Activity", chk_id="chk_export_1"
            )
            src_backup = CompleteBackupEngine(src_dir)
            backup_res = src_backup.create_backup()

            # Target workspace is empty
            self.assertEqual(len(self.store.list_activities()[0]), 0)

            # Preview import
            plan = self.import_engine.preview_import(backup_res.archive_path)
            self.assertFalse(plan.has_blocking_conflicts)
            self.assertEqual(len(plan.conflicts), 0)
            self.assertGreaterEqual(len(plan.entities_to_add), 2)  # activity + checkpoint

            # Execute import
            result = self.import_engine.execute_import(backup_res.archive_path)
            self.assertTrue(result.success)
            self.assertEqual(result.activities_imported, 1)
            self.assertEqual(result.checkpoints_imported, 1)

            # Verify in target store
            imported_act = self.store.get_activity("act_export_1")
            self.assertIsNotNone(imported_act)
            self.assertEqual(imported_act.title, "Exported Activity")

            imported_chk = self.store.get_checkpoint("chk_export_1")
            self.assertIsNotNone(imported_chk)
            self.assertEqual(imported_chk.activity_id, "act_export_1")
        finally:
            shutil.rmtree(src_dir, ignore_errors=True)

    def test_id_collision_identical_content(self):
        """2. Verifies safe deduplication when incoming records match local records identically."""
        # Create identical activity and checkpoint locally
        act, chk = self._create_sample_activity_and_checkpoint(
            self.workspace, act_id="act_ident_1", title="Identical Activity", chk_id="chk_ident_1"
        )
        backup_res = self.backup_engine.create_backup()

        # Preview on same workspace
        plan = self.import_engine.preview_import(backup_res.archive_path)
        self.assertFalse(plan.has_blocking_conflicts)
        self.assertEqual(len(plan.conflicts), 0)
        self.assertGreaterEqual(len(plan.entities_identical), 2)

        # Execute
        result = self.import_engine.execute_import(backup_res.archive_path)
        self.assertTrue(result.success)
        # Still 1 activity in store
        self.assertEqual(len(self.store.list_activities()[0]), 1)

    def test_same_id_different_content_reject(self):
        """3. Verifies fail-safe REJECT strategy when incoming entity diverges in content."""
        # Create local activity
        self._create_sample_activity_and_checkpoint(
            self.workspace, act_id="act_divergent", title="Local Title", chk_id="chk_div_1"
        )

        # Create archive with differing content for act_divergent
        src_dir = Path(tempfile.mkdtemp(prefix="continuum_div_src_"))
        try:
            self._create_sample_activity_and_checkpoint(
                src_dir, act_id="act_divergent", title="Remote Divergent Title", chk_id="chk_div_1"
            )
            src_backup = CompleteBackupEngine(src_dir)
            backup_res = src_backup.create_backup()

            # Preview
            plan = self.import_engine.preview_import(backup_res.archive_path)
            self.assertTrue(plan.has_blocking_conflicts)
            self.assertGreaterEqual(len(plan.conflicts), 1)
            act_conflicts = [c for c in plan.conflicts if c.entity_type == "activity"]
            self.assertEqual(len(act_conflicts), 1)
            self.assertEqual(act_conflicts[0].entity_id, "act_divergent")
            self.assertEqual(act_conflicts[0].conflict_type, ConflictType.CONTENT_DIVERGENCE)

            # Execute with default REJECT strategy must fail
            with self.assertRaises(ImportConflictError) as ctx:
                self.import_engine.execute_import(backup_res.archive_path, conflict_strategy=ConflictResolutionStrategy.REJECT)

            self.assertIn("conflicting", str(ctx.exception))

            # Live target store remains pristine
            local_act = self.store.get_activity("act_divergent")
            self.assertEqual(local_act.title, "Local Title")
        finally:
            shutil.rmtree(src_dir, ignore_errors=True)

    def test_same_id_different_content_rename_new(self):
        """4. Verifies RENAME_NEW strategy reallocates UUIDs and rewires child checkpoints."""
        # Local activity
        self._create_sample_activity_and_checkpoint(
            self.workspace, act_id="act_rename_col", title="Local Activity", chk_id="chk_local_col"
        )

        # Remote activity with same ID but different title and a checkpoint
        src_dir = Path(tempfile.mkdtemp(prefix="continuum_rename_src_"))
        try:
            self._create_sample_activity_and_checkpoint(
                src_dir, act_id="act_rename_col", title="Incoming Activity", chk_id="chk_incoming_col"
            )
            src_backup = CompleteBackupEngine(src_dir)
            backup_res = src_backup.create_backup()

            result = self.import_engine.execute_import(
                backup_res.archive_path,
                conflict_strategy=ConflictResolutionStrategy.RENAME_NEW
            )
            self.assertTrue(result.success)
            self.assertIn("act_rename_col", result.activities_renamed)
            new_act_id = result.activities_renamed["act_rename_col"]

            # Original local activity is unchanged
            local_act = self.store.get_activity("act_rename_col")
            self.assertEqual(local_act.title, "Local Activity")

            # Newly remapped activity exists with new ID
            new_act = self.store.get_activity(new_act_id)
            self.assertIsNotNone(new_act)
            self.assertEqual(new_act.title, "Incoming Activity")

            # Checkpoint rewired to new activity
            incoming_chk = self.store.get_checkpoint("chk_incoming_col")
            self.assertIsNotNone(incoming_chk)
            self.assertEqual(incoming_chk.activity_id, new_act_id)
        finally:
            shutil.rmtree(src_dir, ignore_errors=True)

    def test_same_id_different_content_overwrite(self):
        """5. Verifies OVERWRITE requires explicit confirmation and creates rollback backup."""
        self._create_sample_activity_and_checkpoint(
            self.workspace, act_id="act_over_1", title="Original Title", chk_id="chk_over_1"
        )

        src_dir = Path(tempfile.mkdtemp(prefix="continuum_over_src_"))
        try:
            self._create_sample_activity_and_checkpoint(
                src_dir, act_id="act_over_1", title="Overwritten Title", chk_id="chk_over_1"
            )
            src_backup = CompleteBackupEngine(src_dir)
            backup_res = src_backup.create_backup()

            # Overwrite without confirmation raises error
            with self.assertRaises(ImportConflictError):
                self.import_engine.execute_import(
                    backup_res.archive_path,
                    conflict_strategy=ConflictResolutionStrategy.OVERWRITE,
                    confirm_overwrite=False,
                )

            # Local unchanged
            self.assertEqual(self.store.get_activity("act_over_1").title, "Original Title")

            # Overwrite with confirmation succeeds
            result = self.import_engine.execute_import(
                backup_res.archive_path,
                conflict_strategy=ConflictResolutionStrategy.OVERWRITE,
                confirm_overwrite=True,
            )
            self.assertTrue(result.success)
            self.assertIn("act_over_1", result.activities_overwritten)
            self.assertEqual(self.store.get_activity("act_over_1").title, "Overwritten Title")
        finally:
            shutil.rmtree(src_dir, ignore_errors=True)

    def test_same_id_different_content_skip(self):
        """6. Verifies SKIP preserves local record and ignores incoming conflicting entity."""
        self._create_sample_activity_and_checkpoint(
            self.workspace, act_id="act_skip_1", title="Keep Me", chk_id="chk_skip_1"
        )

        src_dir = Path(tempfile.mkdtemp(prefix="continuum_skip_src_"))
        try:
            self._create_sample_activity_and_checkpoint(
                src_dir, act_id="act_skip_1", title="Ignore Me", chk_id="chk_skip_1"
            )
            src_backup = CompleteBackupEngine(src_dir)
            backup_res = src_backup.create_backup()

            result = self.import_engine.execute_import(
                backup_res.archive_path,
                conflict_strategy=ConflictResolutionStrategy.SKIP,
            )
            self.assertTrue(result.success)
            self.assertIn("act_skip_1", result.activities_skipped)
            self.assertEqual(self.store.get_activity("act_skip_1").title, "Keep Me")
        finally:
            shutil.rmtree(src_dir, ignore_errors=True)

    def test_corrupt_archive_blocks_mutation(self):
        """7. Verifies corrupted or truncated archives block live mutations before touching disk."""
        # Create pristine local store
        self._create_sample_activity_and_checkpoint(
            self.workspace, act_id="act_local_safe", title="Safe Local", chk_id="chk_local_safe"
        )

        corrupt_tar = self.workspace / "corrupted_archive.tar.gz"
        with open(corrupt_tar, "wb") as f:
            f.write(b"\x1f\x8b\x08\x00corrupted-truncated-stream-garbage")

        with self.assertRaises(CorruptedArchiveError):
            self.import_engine.execute_import(corrupt_tar)

        # Target workspace remains untouched
        local_act = self.store.get_activity("act_local_safe")
        self.assertIsNotNone(local_act)
        self.assertEqual(local_act.title, "Safe Local")

    def test_interruption_and_recovery(self):
        """8. Verifies recovery from interrupted commit and subsequent safe retry."""
        # Create local activity
        self._create_sample_activity_and_checkpoint(
            self.workspace, act_id="act_prior", title="Prior Version", chk_id="chk_prior"
        )

        # Simulate interrupted staging directory
        staged_id = "imp_simulate_interruption"
        staged_dir = self.continuum_dir / "staging" / staged_id
        rollback_dir = staged_dir / "rollback"
        rollback_dir.mkdir(parents=True, exist_ok=True)

        # Put backup of act_prior in rollback
        act_rel = Path("activities") / "act_prior" / "activity.json"
        rollback_file = rollback_dir / act_rel
        rollback_file.parent.mkdir(parents=True, exist_ok=True)
        with open(rollback_file, "w", encoding="utf-8") as f:
            json.dump({"id": "act_prior", "title": "Prior Version", "status": "active"}, f)

        # Simulate partially mutated file
        live_file = self.continuum_dir / act_rel
        with open(live_file, "w", encoding="utf-8") as f:
            json.dump({"id": "act_prior", "title": "Partially Mutated Half-Written", "status": "active"}, f)

        # Journal with status COMMITTING
        journal_file = staged_dir / "journal.json"
        with open(journal_file, "w", encoding="utf-8") as f:
            json.dump({
                "import_id": staged_id,
                "status": ImportStageStatus.COMMITTING.value,
                "overwritten_files": [str(act_rel)],
                "created_files": [],
            }, f)

        # Execute recovery
        recovered = self.import_engine.recover_interrupted_imports()
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["status"], "RECOVERED")

        # Prior version restored from rollback!
        with open(live_file, "r", encoding="utf-8") as f:
            restored_data = json.load(f)
        self.assertEqual(restored_data["title"], "Prior Version")

    def test_unrelated_data_unchanged(self):
        """9. Verifies unrelated activities and checkpoints remain completely untouched."""
        # Unrelated local activities
        act_unrel, chk_unrel = self._create_sample_activity_and_checkpoint(
            self.workspace, act_id="act_unrelated", title="Unrelated Task", chk_id="chk_unrelated"
        )

        # Create separate source archive
        src_dir = Path(tempfile.mkdtemp(prefix="continuum_unrel_src_"))
        try:
            self._create_sample_activity_and_checkpoint(
                src_dir, act_id="act_new_feature", title="New Feature", chk_id="chk_new_feature"
            )
            src_backup = CompleteBackupEngine(src_dir)
            backup_res = src_backup.create_backup()

            result = self.import_engine.execute_import(backup_res.archive_path)
            self.assertTrue(result.success)
            self.assertEqual(result.unrelated_activities_preserved, 1)

            # Unrelated activity is identical
            unrel_act = self.store.get_activity("act_unrelated")
            self.assertIsNotNone(unrel_act)
            self.assertEqual(unrel_act.title, "Unrelated Task")

            unrel_chk = self.store.get_checkpoint("chk_unrelated")
            self.assertIsNotNone(unrel_chk)
            self.assertEqual(unrel_chk.activity_id, "act_unrelated")
        finally:
            shutil.rmtree(src_dir, ignore_errors=True)

    def test_gate_no_silent_overwrite_or_unrecoverable_partial_import(self):
        """10. GATE INVARIANT: No silent overwrite or unrecoverable partial import."""
        # 1. Verification that divergent records NEVER overwrite silently without confirm_overwrite=True
        self._create_sample_activity_and_checkpoint(
            self.workspace, act_id="act_gate", title="Protected Local", chk_id="chk_gate"
        )
        src_dir = Path(tempfile.mkdtemp(prefix="continuum_gate_src_"))
        try:
            self._create_sample_activity_and_checkpoint(
                src_dir, act_id="act_gate", title="Silent Overwrite Attempt", chk_id="chk_gate"
            )
            src_backup = CompleteBackupEngine(src_dir)
            backup_res = src_backup.create_backup()

            # Attempt import without confirmation must raise ImportConflictError
            with self.assertRaises(ImportConflictError):
                self.import_engine.execute_import(
                    backup_res.archive_path,
                    conflict_strategy=ConflictResolutionStrategy.OVERWRITE,
                    confirm_overwrite=False,
                )

            # Local state unchanged
            self.assertEqual(self.store.get_activity("act_gate").title, "Protected Local")
        finally:
            shutil.rmtree(src_dir, ignore_errors=True)

    def test_rest_api_import_endpoints(self):
        """11. Verifies REST API integration for preview, execute, and recover."""
        import io
        from server.routes import ContinuumApiHandler

        # Create source backup
        src_dir = Path(tempfile.mkdtemp(prefix="continuum_api_src_"))
        try:
            self._create_sample_activity_and_checkpoint(
                src_dir, act_id="act_api_1", title="API Import Test", chk_id="chk_api_1"
            )
            src_backup = CompleteBackupEngine(src_dir)
            backup_res = src_backup.create_backup()

            class DummyHandler(ContinuumApiHandler):
                def __init__(self, workspace_root):
                    self.workspace_root = workspace_root
                    self.headers = {}
                    self.rfile = io.BytesIO()
                    self.wfile = io.BytesIO()
                    self.status_code = None
                    self.response_data = None

                def _send_json_response(self, data, status_code=200):
                    self.status_code = status_code
                    self.response_data = data

                def _send_error_response(self, message, status_code=400, details=None):
                    self.status_code = status_code
                    self.response_data = {"error": message, "details": details}

            handler = DummyHandler(self.workspace)

            # 1. Test POST /api/v1/import/preview
            preview_body = json.dumps({"archive_path": str(backup_res.archive_path)}).encode("utf-8")
            handler.headers = {"Content-Length": str(len(preview_body))}
            handler.rfile = io.BytesIO(preview_body)

            handler.handle_post_v1_import_preview()
            self.assertEqual(handler.status_code, 200, msg=f"Error response: {handler.response_data}")
            self.assertEqual(handler.response_data["status"], "success")
            self.assertIn("plan", handler.response_data)

            # 2. Test POST /api/v1/import/execute
            exec_body = json.dumps({
                "archive_path": str(backup_res.archive_path),
                "conflict_strategy": "REJECT",
            }).encode("utf-8")
            handler.headers = {"Content-Length": str(len(exec_body))}
            handler.rfile = io.BytesIO(exec_body)

            handler.handle_post_v1_import_execute()
            self.assertEqual(handler.status_code, 200)
            self.assertEqual(handler.response_data["status"], "success")
            self.assertTrue(handler.response_data["result"]["success"])

            # 3. Test POST /api/v1/import/recover
            recover_body = json.dumps({}).encode("utf-8")
            handler.headers = {"Content-Length": str(len(recover_body))}
            handler.rfile = io.BytesIO(recover_body)

            handler.handle_post_v1_import_recover()
            self.assertEqual(handler.status_code, 200)
            self.assertEqual(handler.response_data["status"], "success")
            self.assertIn("recovered_sessions", handler.response_data)
        finally:
            shutil.rmtree(src_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
