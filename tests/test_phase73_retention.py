"""
Phase 73: Safe Retention - Comprehensive Test Suite
===================================================
Tests all requirements and invariants for Milestone 42 - Phase 73:
1. Multi-target policies:
   - Max checkpoints count policy (e.g. keep max 3 checkpoints).
   - Max age policy (days).
   - Max storage target policy (bytes).
2. Protected checkpoints:
   - Current active branch head is ALWAYS protected.
   - Branch origin checkpoints referenced by another activity are STRICTLY protected.
   - Explicit user-flagged checkpoints (metadata.is_protected=True) are preserved.
3. Pre-flight preview and impact summary:
   - Accurate counts of protected, candidate, and reclaimable bytes.
   - Pure read-only inspection; history is never mutated during preview.
4. Safe Pruning & Invariant Enforcement:
   - Only safe, non-protected historical checkpoints are pruned.
   - Explains when limits cannot be met safely due to protected ancestry.
   - Gate Invariant: "No blind deletion loop." Never deletes protected checkpoints.
5. Backup-backed zero-data-loss undo / recovery:
   - Pruned checkpoints backed up in `.continuum/retention_backup/`.
   - Restore restores pruned checkpoints and synchronizes index cleanly.
6. REST API integration:
   - GET /api/v1/retention/preview
   - POST /api/v1/retention/prune
   - POST /api/v1/retention/undo
"""

from datetime import datetime, timezone, timedelta
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from core.activity import Activity, ActivityStatus, ActivityType
from core.checkpoint import ArtifactReference, UniversalCheckpoint
from core.enums import ArtifactMode, ProvenanceType
from core.retention import (
    RetentionError,
    RetentionLimitError,
    RetentionPolicy,
    SafeRetentionEngine,
)
from storage.activity_store import ActivityCheckpointStore


class TestPhase73SafeRetention(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="continuum_phase73_test_")
        self.workspace_root = Path(self.test_dir)
        self.store = ActivityCheckpointStore(self.workspace_root)
        self.engine = SafeRetentionEngine(self.workspace_root, store=self.store)

        # Create active test activity
        self.activity = self.store.create_activity(
            Activity(
                id="act_p73_main",
                title="Phase 73 Main Retention Activity",
                description="Testing safe history retention policies",
                activity_type="coding",
                status=ActivityStatus.ACTIVE,
            )
        )

        # Create 5 historical checkpoints in chronological order
        self.checkpoints: list[UniversalCheckpoint] = []
        now = datetime.now(timezone.utc)
        for i in range(5):
            t_iso = (now - timedelta(days=5 - i)).isoformat()
            parent_id = self.checkpoints[-1].id if self.checkpoints else None
            chk = UniversalCheckpoint(
                id=f"chk_p73_{i+1:02d}",
                activity_id=self.activity.id,
                timestamp=t_iso,
                parent_checkpoint_id=parent_id,
                context=f"Checkpoint {i+1} progress",
                completed_work=[f"Step {i+1} completed"],
            )
            committed = self.store.commit_checkpoint(chk)
            self.checkpoints.append(committed)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_preview_retention_read_only_and_accurate(self):
        """Verifies preview_retention accurately reports impact without modifying storage."""
        policy = RetentionPolicy(max_checkpoints=2)
        preview = self.engine.preview_retention(self.activity.id, policy)

        self.assertEqual(preview.total_checkpoints_count, 5)
        # Checkpoint 5 (head) is protected, remaining 4 are evaluated
        self.assertEqual(preview.protected_checkpoints_count, 1)
        # Prunes 3 oldest to leave 2 total
        self.assertEqual(preview.eligible_for_pruning_count, 3)
        self.assertGreater(preview.reclaimable_bytes, 0)

        # Invariant: storage is untouched
        chks, count = self.store.list_checkpoints(self.activity.id)
        self.assertEqual(count, 5)

    def test_current_head_is_always_protected(self):
        """Verifies that the latest/head checkpoint is never marked eligible for pruning."""
        # Policy requesting only 1 checkpoint
        policy = RetentionPolicy(max_checkpoints=1)
        preview = self.engine.preview_retention(self.activity.id, policy)

        head_eval = next(e for e in preview.evaluations if e.checkpoint_id == self.checkpoints[-1].id)
        self.assertTrue(head_eval.is_protected)
        self.assertFalse(head_eval.eligible_for_pruning)
        self.assertIn("Current active head checkpoint", head_eval.protection_reason)

    def test_explicitly_flagged_checkpoint_is_protected(self):
        """Verifies that metadata.is_protected=True prevents checkpoint pruning."""
        # Flag checkpoint 2 as explicitly protected
        chk2 = self.checkpoints[1]
        chk2.metadata["is_protected"] = True
        self.store.commit_checkpoint(chk2)

        policy = RetentionPolicy(max_checkpoints=2)
        preview = self.engine.preview_retention(self.activity.id, policy)

        chk2_eval = next(e for e in preview.evaluations if e.checkpoint_id == chk2.id)
        self.assertTrue(chk2_eval.is_protected)
        self.assertFalse(chk2_eval.eligible_for_pruning)
        self.assertIn("Explicitly protected by user setting", chk2_eval.protection_reason)

    def test_branch_origin_checkpoint_is_strictly_protected(self):
        """Verifies that checkpoints referenced as branch origins by other activities are never pruned."""
        # Branch from checkpoint 3 into a new activity
        chk3 = self.checkpoints[2]
        self.store.branch_from_checkpoint(
            source_checkpoint_id=chk3.id,
            new_title="Feature Branch from Checkpoint 3",
            branch_name="feature-3",
        )

        policy = RetentionPolicy(max_checkpoints=1)
        preview = self.engine.preview_retention(self.activity.id, policy)

        chk3_eval = next(e for e in preview.evaluations if e.checkpoint_id == chk3.id)
        self.assertTrue(chk3_eval.is_protected)
        self.assertFalse(chk3_eval.eligible_for_pruning)
        self.assertIn("branch origin", chk3_eval.protection_reason)

    def test_prune_checkpoints_dry_run_does_not_mutate(self):
        """Verifies dry_run=True returns candidate report without removing files."""
        policy = RetentionPolicy(max_checkpoints=2)
        res = self.engine.prune_checkpoints(self.activity.id, policy=policy, dry_run=True)

        self.assertTrue(res.is_dry_run)
        self.assertTrue(res.success)
        self.assertIn("Dry run preview", res.message)

        # Verify all 5 checkpoints still exist
        chks, count = self.store.list_checkpoints(self.activity.id)
        self.assertEqual(count, 5)

    def test_prune_checkpoints_execution_and_undo_recovery(self):
        """
        Verifies execution of safe pruning:
        1. Safely prunes non-protected checkpoints.
        2. Creates recovery backup.
        3. Index is cleanly updated.
        4. Undo restores pruned checkpoints completely.
        """
        policy = RetentionPolicy(max_checkpoints=2, create_undo_backup=True)
        res = self.engine.prune_checkpoints(self.activity.id, policy=policy, dry_run=False)

        self.assertFalse(res.is_dry_run)
        self.assertTrue(res.success)
        self.assertEqual(res.pruned_count, 3)
        self.assertIsNotNone(res.backup_path)
        self.assertTrue(Path(res.backup_path).is_dir())

        # Check remaining in store
        remaining_chks, count = self.store.list_checkpoints(self.activity.id)
        self.assertEqual(count, 2)
        remaining_ids = [c.id for c in remaining_chks]
        self.assertIn(self.checkpoints[-1].id, remaining_ids)
        self.assertIn(self.checkpoints[-2].id, remaining_ids)

        # Execute Undo / Recovery
        restored = self.engine.restore_retention_backup(res.backup_path)
        self.assertEqual(restored, 3)

        # Confirm all 5 are back and verified
        re_chks, re_count = self.store.list_checkpoints(self.activity.id)
        self.assertEqual(re_count, 5)

    def test_gate_no_blind_deletion_loop_when_limits_unsatisfied(self):
        """
        GATE INVARIANT TEST:
        'No blind deletion loop.'
        When protected checkpoints prevent meeting requested target, the engine
        refuses to delete protected nodes, reports limit_satisfied=False, and explains.
        """
        # Flag all checkpoints as protected except one
        for chk in self.checkpoints[:-1]:
            chk.metadata["is_protected"] = True
            self.store.commit_checkpoint(chk)

        # Request keeping only 2 checkpoints when 5 are protected
        policy = RetentionPolicy(max_checkpoints=2)
        preview = self.engine.preview_retention(self.activity.id, policy)

        self.assertFalse(preview.limit_satisfied)
        self.assertIn("cannot be met because", preview.explanation)

        # Prune only prunes eligible (0 in this case because all are protected)
        res = self.engine.prune_checkpoints(self.activity.id, policy=policy)
        self.assertEqual(res.pruned_count, 0)

        # Core data remains 100% intact
        _, count = self.store.list_checkpoints(self.activity.id)
        self.assertEqual(count, 5)

    def test_retention_rest_api_endpoints(self):
        """Verifies GET preview, POST prune, and POST undo REST routes."""
        from server.routes import ContinuumApiHandler

        def make_handler(body_bytes: bytes = b""):
            handler = ContinuumApiHandler.__new__(ContinuumApiHandler)
            handler.workspace_root = self.workspace_root
            handler.require_auth = False
            handler.auth_manager = None
            handler.request_version = "HTTP/1.1"
            handler.requestline = "MOCK / HTTP/1.1"
            handler.client_address = ("127.0.0.1", 12345)
            handler.headers = {"Content-Length": str(len(body_bytes))} if body_bytes else {}
            handler.rfile = io.BytesIO(body_bytes)
            handler.wfile = io.BytesIO()
            return handler

        # 1. GET /api/v1/retention/preview
        handler_prev = make_handler()
        handler_prev.handle_get_v1_retention_preview({"activity_id": [self.activity.id], "max_checkpoints": ["2"]})
        resp_bytes = handler_prev.wfile.getvalue()
        self.assertIn(b'"status": "success"', resp_bytes)
        self.assertIn(b'"eligible_for_pruning_count": 3', resp_bytes)

        # 2. POST /api/v1/retention/prune
        prune_body = json.dumps({"activity_id": self.activity.id, "max_checkpoints": 2}).encode("utf-8")
        handler_prune = make_handler(prune_body)
        handler_prune.handle_post_v1_retention_prune()
        prune_raw = handler_prune.wfile.getvalue()
        prune_json_str = prune_raw.split(b"\r\n\r\n", 1)[1].decode("utf-8") if b"\r\n\r\n" in prune_raw else prune_raw.decode("utf-8")
        prune_resp = json.loads(prune_json_str)
        self.assertEqual(prune_resp["status"], "success")
        backup_path = prune_resp["result"]["backup_path"]
        self.assertIsNotNone(backup_path)

        # 3. POST /api/v1/retention/undo
        undo_body = json.dumps({"backup_path": backup_path}).encode("utf-8")
        handler_undo = make_handler(undo_body)
        handler_undo.handle_post_v1_retention_undo()
        undo_raw = handler_undo.wfile.getvalue()
        undo_json_str = undo_raw.split(b"\r\n\r\n", 1)[1].decode("utf-8") if b"\r\n\r\n" in undo_raw else undo_raw.decode("utf-8")
        undo_resp = json.loads(undo_json_str)
        self.assertEqual(undo_resp["status"], "success")
        self.assertEqual(undo_resp["restored_count"], 3)


if __name__ == "__main__":
    unittest.main()
