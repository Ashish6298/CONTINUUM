"""
Project Continuum — Phase 66: Explicit Restore and Recovery Tests
==================================================================
Milestone 39: History, Diffs, Branch and Restore
Phase 66: Explicit Restore and Recovery

Validates:
1. Separate confirmed restore action with pre-flight working state delta explanation.
2. Gate Invariant: No silent deletion or unrecoverable partial restore.
   All newer checkpoints remain 100% preserved; restore appends a new checkpoint.
3. Compatibility validation across activities, non-existent checkpoints, and schemas.
4. Cancel flow (preview without confirm leaves state untouched).
5. Concurrency checks (expected_head_checkpoint_id) and transaction rollback safety.
6. Repeated restores back and forth across history.
7. REST API endpoints (POST /api/v1/checkpoints/restore/preview & POST /api/v1/checkpoints/restore/confirm).
"""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
import urllib.request
import urllib.error

from core.activity import Activity, ActivityStatus, ActivityType
from core.checkpoint import (
    UniversalCheckpoint,
    DecisionRecord,
    ArtifactReference,
    ProvenanceRecord,
    CheckpointValidationError,
)
from core.enums import ArtifactMode, ProvenanceType
from core.invariants import CommitFailedError
from storage.activity_store import (
    ActivityCheckpointStore,
    ActivityNotFoundError,
    CheckpointNotFoundError,
    IncompatibleRestoreError,
)
from server.daemon import ContinuumHttpDaemon


class TestPhase66Restore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="continuum_p66_test_")
        self.workspace_root = Path(self.temp_dir)
        self.store = ActivityCheckpointStore(str(self.workspace_root))

        # Create active test activity
        self.activity = Activity(
            id="act_restore_main",
            title="Database Migration Subsystem",
            description="Implementing durable transactional migration and recovery.",
            activity_type=ActivityType.CODING,
            status=ActivityStatus.ACTIVE,
        )
        self.store.create_activity(self.activity)

        # 3 sequential checkpoints representing history
        self.chk1 = UniversalCheckpoint(
            id="chk_hist_001",
            activity_id=self.activity.id,
            timestamp="2026-10-15T10:00:00Z",
            progress={"percentage": 20.0},
            completed_work=["Define table schemas"],
            pending_actions=["Write migration runner", "Add integrity checks"],
            decisions=[DecisionRecord(id="dec_01", decision="SQLite WAL mode", rationale="Performance")],
            blockers=["Uncertain about Windows file lock behavior"],
            context="Initial migration models created.",
            artifacts=[
                ArtifactReference(
                    name="schema.sql",
                    path_or_uri="storage/schema.sql",
                    mode=ArtifactMode.REFERENCE,
                )
            ],
        )
        self.store.commit_checkpoint(self.chk1)

        self.chk2 = UniversalCheckpoint(
            id="chk_hist_002",
            activity_id=self.activity.id,
            timestamp="2026-10-15T12:00:00Z",
            parent_checkpoint_id=self.chk1.id,
            progress={"percentage": 50.0},
            completed_work=["Define table schemas", "Write migration runner"],
            pending_actions=["Add integrity checks"],
            decisions=[
                DecisionRecord(id="dec_01", decision="SQLite WAL mode", rationale="Performance"),
                DecisionRecord(id="dec_02", decision="Atomic temp rename", rationale="Crash safety"),
            ],
            blockers=[],
            context="Migration runner completed.",
        )
        self.store.commit_checkpoint(self.chk2)

        self.chk3 = UniversalCheckpoint(
            id="chk_hist_003",
            activity_id=self.activity.id,
            timestamp="2026-10-15T14:00:00Z",
            parent_checkpoint_id=self.chk2.id,
            progress={"percentage": 80.0},
            completed_work=["Define table schemas", "Write migration runner", "Add integrity checks"],
            pending_actions=["Deploy to production canary"],
            decisions=[
                DecisionRecord(id="dec_01", decision="SQLite WAL mode", rationale="Performance"),
                DecisionRecord(id="dec_02", decision="Atomic temp rename", rationale="Crash safety"),
                DecisionRecord(id="dec_03", decision="Automatic rollback on error", rationale="Integrity"),
            ],
            blockers=[],
            context="Integrity verification implemented; preparing canary deployment.",
        )
        self.store.commit_checkpoint(self.chk3)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_restore_preview_explains_working_state_changes(self):
        """
        Verify that preview_restore calculates exact working state differences
        between current head (chk3) and target historical checkpoint (chk1)
        without mutating any records.
        """
        preview = self.store.preview_restore(self.chk1.id, self.activity.id)

        self.assertEqual(preview["activity_id"], self.activity.id)
        self.assertEqual(preview["current_head_checkpoint_id"], self.chk3.id)
        self.assertEqual(preview["target_checkpoint_id"], self.chk1.id)
        self.assertFalse(preview["is_current_head"])
        self.assertEqual(preview["newer_checkpoints_preserved_count"], 2)  # chk2 and chk3 are newer than chk1

        points = preview["explanation_points"]
        self.assertTrue(any("roll back from 80.0% to 20.0%" in p for p in points))
        self.assertTrue(any("completed work item(s) from newer checkpoints will be rolled back" in p for p in points))
        self.assertTrue(any("earlier pending action(s) will be reinstated" in p for p in points))
        self.assertTrue(any("newer decision(s) will be superseded" in p for p in points))
        self.assertTrue(any("earlier blocker(s) will be reinstated" in p for p in points))

        # Verify nothing was mutated
        head_list, total = self.store.list_checkpoints(self.activity.id)
        self.assertEqual(total, 3)
        self.assertEqual(head_list[0].id, self.chk3.id)

    def test_successful_restore_and_state_reinstatement(self):
        """
        Verify that confirming a restore creates a new checkpoint appended to the timeline
        with state accurately reinstated from the target historical checkpoint.
        """
        act, restored_chk = self.store.confirm_restore(
            target_checkpoint_id=self.chk1.id,
            activity_id=self.activity.id,
            reason="Canary deployment failed; reverting to pre-migration runner state",
        )

        self.assertNotEqual(restored_chk.id, self.chk1.id)
        self.assertNotEqual(restored_chk.id, self.chk3.id)
        # Parent is prior head (chk3), maintaining forward chronological timeline linearity
        self.assertEqual(restored_chk.parent_checkpoint_id, self.chk3.id)

        # Metadata records restore provenance
        self.assertEqual(restored_chk.metadata["restored_from_checkpoint_id"], self.chk1.id)
        self.assertEqual(restored_chk.metadata["prior_head_checkpoint_id"], self.chk3.id)
        self.assertEqual(
            restored_chk.metadata["restore_reason"],
            "Canary deployment failed; reverting to pre-migration runner state",
        )

        # State reinstated from chk1
        self.assertEqual(restored_chk.progress.get("percentage"), 20.0)
        self.assertEqual(restored_chk.completed_work, ["Define table schemas"])
        self.assertEqual(restored_chk.pending_actions, ["Write migration runner", "Add integrity checks"])
        self.assertEqual(len(restored_chk.decisions), 1)
        self.assertEqual(restored_chk.decisions[0].decision, "SQLite WAL mode")
        self.assertEqual(restored_chk.blockers, ["Uncertain about Windows file lock behavior"])
        self.assertEqual(len(restored_chk.artifacts), 1)
        self.assertEqual(restored_chk.artifacts[0].name, "schema.sql")

        # Context has explicit restore indicator
        self.assertIn(f"[Restored from {self.chk1.id}]", restored_chk.context)

    def test_gate_no_silent_deletion_newer_history_preserved(self):
        """
        Gate Invariant: No silent deletion or unrecoverable partial restore.
        Restoring to an older checkpoint (chk1) MUST preserve checkpoints 2 and 3.
        """
        # Execute restore
        act, restored_chk = self.store.confirm_restore(
            target_checkpoint_id=self.chk1.id,
            activity_id=self.activity.id,
        )

        # 1. Verify all 4 checkpoints exist in authoritative JSON files
        chk1_loaded = self.store.get_checkpoint(self.chk1.id, self.activity.id)
        chk2_loaded = self.store.get_checkpoint(self.chk2.id, self.activity.id)
        chk3_loaded = self.store.get_checkpoint(self.chk3.id, self.activity.id)
        restored_loaded = self.store.get_checkpoint(restored_chk.id, self.activity.id)

        self.assertIsNotNone(chk1_loaded)
        self.assertIsNotNone(chk2_loaded)
        self.assertIsNotNone(chk3_loaded)
        self.assertIsNotNone(restored_loaded)

        # 2. Verify list_checkpoints in ascending chronological order
        chks_asc, total = self.store.list_checkpoints(self.activity.id, order="asc")
        self.assertEqual(total, 4)
        self.assertEqual([c.id for c in chks_asc], [self.chk1.id, self.chk2.id, self.chk3.id, restored_chk.id])

        # 3. Newest checkpoint is the restored checkpoint
        chks_desc, _ = self.store.list_checkpoints(self.activity.id, order="desc")
        self.assertEqual(chks_desc[0].id, restored_chk.id)

    def test_restore_cancel_flow(self):
        """
        Simulate user inspecting preview and deciding to cancel.
        Verifies that no changes are committed when confirm_restore is not called.
        """
        preview = self.store.preview_restore(self.chk2.id, self.activity.id)
        self.assertIsNotNone(preview)

        # User cancels; verify total checkpoints remain 3
        chks, total = self.store.list_checkpoints(self.activity.id)
        self.assertEqual(total, 3)
        self.assertEqual(chks[0].id, self.chk3.id)

    def test_incompatibility_validation(self):
        """
        Verify that restoring across incompatible activities or invalid inputs
        is safely rejected with descriptive errors.
        """
        # Create second distinct activity
        other_act = Activity(id="act_other_system", title="Other Activity")
        self.store.create_activity(other_act)

        other_chk = UniversalCheckpoint(
            id="chk_other_001",
            activity_id=other_act.id,
            context="Other activity state",
        )
        self.store.commit_checkpoint(other_chk)

        # 1. Attempt restore of other_chk into self.activity -> IncompatibleRestoreError
        with self.assertRaises(IncompatibleRestoreError):
            self.store.preview_restore(other_chk.id, self.activity.id)

        with self.assertRaises(IncompatibleRestoreError):
            self.store.confirm_restore(other_chk.id, self.activity.id)

        # 2. Non-existent checkpoint -> CheckpointNotFoundError
        with self.assertRaises(CheckpointNotFoundError):
            self.store.preview_restore("chk_ghost_999", self.activity.id)

        with self.assertRaises(CheckpointNotFoundError):
            self.store.confirm_restore("chk_ghost_999", self.activity.id)

        # 3. Malformed input
        with self.assertRaises(CheckpointValidationError):
            self.store.preview_restore("", self.activity.id)

    def test_concurrency_conflict_safety(self):
        """
        Verify that if expected_head_checkpoint_id does not match the actual current head,
        the restore fails immediately without corrupting state.
        """
        with self.assertRaises(CommitFailedError) as ctx:
            self.store.confirm_restore(
                target_checkpoint_id=self.chk1.id,
                activity_id=self.activity.id,
                expected_head_checkpoint_id="chk_outdated_head",
            )
        self.assertIn("Concurrency conflict", str(ctx.exception))

        # Checkpoints remain 3
        _, total = self.store.list_checkpoints(self.activity.id)
        self.assertEqual(total, 3)

    def test_repeated_restore(self):
        """
        Verify that multiple sequential restores back and forth across history
        maintain a complete, coherent, non-destructive timeline.
        """
        # 1. First restore: restore to chk1
        _, chk4 = self.store.confirm_restore(self.chk1.id, self.activity.id, reason="Restore 1: back to chk1")
        self.assertEqual(chk4.progress.get("percentage"), 20.0)

        # 2. Second restore: restore back to chk3
        _, chk5 = self.store.confirm_restore(self.chk3.id, self.activity.id, reason="Restore 2: forward to chk3 state")
        self.assertEqual(chk5.progress.get("percentage"), 80.0)

        # Verify lineage: 5 checkpoints in total
        chks_asc, total = self.store.list_checkpoints(self.activity.id, order="asc")
        self.assertEqual(total, 5)
        self.assertEqual([c.id for c in chks_asc], [self.chk1.id, self.chk2.id, self.chk3.id, chk4.id, chk5.id])
        self.assertEqual(chk5.parent_checkpoint_id, chk4.id)
        self.assertEqual(chk5.metadata["restored_from_checkpoint_id"], self.chk3.id)


class TestPhase66RestoreApi(unittest.TestCase):
    """Integration tests for HTTP endpoints POST /api/v1/checkpoints/restore/preview & /confirm."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="continuum_p66_api_")
        cls.workspace = Path(cls.temp_dir)

        cls.store = ActivityCheckpointStore(str(cls.workspace))
        cls.act = Activity(id="act_api_restore", title="API Restore Test Activity")
        cls.store.create_activity(cls.act)

        cls.chk1 = UniversalCheckpoint(
            id="chk_api_r1",
            activity_id=cls.act.id,
            timestamp="2026-10-15T10:00:00Z",
            progress={"percentage": 30.0},
            completed_work=["Step A"],
        )
        cls.store.commit_checkpoint(cls.chk1)

        cls.chk2 = UniversalCheckpoint(
            id="chk_api_r2",
            activity_id=cls.act.id,
            timestamp="2026-10-15T12:00:00Z",
            parent_checkpoint_id=cls.chk1.id,
            progress={"percentage": 90.0},
            completed_work=["Step A", "Step B", "Step C"],
        )
        cls.store.commit_checkpoint(cls.chk2)

        # Start daemon
        cls.daemon = ContinuumHttpDaemon(cls.temp_dir, host="127.0.0.1", default_port=8970)
        cls.status = cls.daemon.start(run_in_background=True)
        cls.token = cls.daemon.auth_manager.get_token() or ""
        cls.base_url = cls.status.server_url

    @classmethod
    def tearDownClass(cls):
        cls.daemon.stop()
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def _post(self, path: str, payload: dict):
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Continuum-Token", self.token)
        return urllib.request.urlopen(req, timeout=5)

    def test_api_restore_preview_success(self):
        act = Activity(id="act_api_prev", title="API Prev")
        self.store.create_activity(act)
        c1 = UniversalCheckpoint(id="chk_prev_1", activity_id=act.id, timestamp="2026-10-15T10:00:00Z", progress={"percentage": 30.0})
        c2 = UniversalCheckpoint(id="chk_prev_2", activity_id=act.id, timestamp="2026-10-15T12:00:00Z", parent_checkpoint_id=c1.id, progress={"percentage": 90.0})
        self.store.commit_checkpoint(c1)
        self.store.commit_checkpoint(c2)

        payload = {
            "target_checkpoint_id": c1.id,
            "activity_id": act.id,
        }
        res = self._post("/api/v1/checkpoints/restore/preview", payload)
        self.assertEqual(res.status, 200)
        data = json.loads(res.read().decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["preview"]["current_head_checkpoint_id"], c2.id)
        self.assertEqual(data["preview"]["target_checkpoint_id"], c1.id)
        self.assertEqual(data["preview"]["newer_checkpoints_preserved_count"], 1)

    def test_api_restore_confirm_success(self):
        act = Activity(id="act_api_conf", title="API Conf")
        self.store.create_activity(act)
        c1 = UniversalCheckpoint(id="chk_conf_1", activity_id=act.id, timestamp="2026-10-15T10:00:00Z", progress={"percentage": 30.0})
        c2 = UniversalCheckpoint(id="chk_conf_2", activity_id=act.id, timestamp="2026-10-15T12:00:00Z", parent_checkpoint_id=c1.id, progress={"percentage": 90.0})
        self.store.commit_checkpoint(c1)
        self.store.commit_checkpoint(c2)

        payload = {
            "target_checkpoint_id": c1.id,
            "activity_id": act.id,
            "reason": "API test revert",
        }
        res = self._post("/api/v1/checkpoints/restore/confirm", payload)
        self.assertEqual(res.status, 201)
        data = json.loads(res.read().decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["restored_checkpoint"]["progress"]["percentage"], 30.0)
        self.assertEqual(data["restored_checkpoint"]["metadata"]["restored_from_checkpoint_id"], c1.id)

    def test_api_restore_missing_target(self):
        payload = {"activity_id": "act_api_conf"}
        try:
            self._post("/api/v1/checkpoints/restore/preview", payload)
            self.fail("Expected HTTPError 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)


if __name__ == "__main__":
    unittest.main()
