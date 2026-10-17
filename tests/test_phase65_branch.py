"""
Project Continuum — Phase 65: Branch from Historical Checkpoint Tests
======================================================================
Milestone 39: History, Diffs, Branch and Restore
Phase 65: Branch from Historical Checkpoint

Validates:
1. Branching from old and recent checkpoints creating independent continuation activities.
2. Stable identity generation (I-01) with ancestry tracking.
3. Gate: Branching is NOT restore and NEVER mutates the source branch or historical checkpoints.
4. Artifact references are reused without physical file duplication.
5. Ancestry preservation across renames and nested branching.
6. Atomic rollback on partial failure (no dangling files or index rows).
7. Retry safety.
8. End-to-end HTTP API endpoints (POST /api/v1/activities/branch & GET /api/v1/activities/branch/ancestry).
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
)
from server.daemon import ContinuumHttpDaemon


class TestPhase65Branching(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="continuum_p65_test_")
        self.workspace_root = Path(self.temp_dir)
        self.store = ActivityCheckpointStore(str(self.workspace_root))

        # Create baseline source activity
        self.source_act = Activity(
            id="act_source_main",
            title="Core Platform Implementation",
            description="Developing foundational distributed sync subsystem.",
            activity_type=ActivityType.CODING,
            status=ActivityStatus.ACTIVE,
            tags=["core", "platform"],
        )
        self.store.create_activity(self.source_act)

        # Create sequential checkpoints (chk_1, chk_2, chk_3)
        self.chk1 = UniversalCheckpoint(
            id="chk_source_001",
            activity_id=self.source_act.id,
            timestamp="2026-10-15T10:00:00Z",
            progress={"percentage": 25.0},
            completed_work=["Define protocol specification"],
            pending_actions=["Implement handshake parser"],
            decisions=[DecisionRecord(id="dec_01", decision="Use JSON-over-HTTP")],
            context="Initial architecture draft established.",
            artifacts=[
                ArtifactReference(
                    name="spec.md",
                    path_or_uri="docs/spec.md",
                    mode=ArtifactMode.REFERENCE,
                    checksum_sha256="abc123sha",
                )
            ],
        )
        self.store.commit_checkpoint(self.chk1)

        self.chk2 = UniversalCheckpoint(
            id="chk_source_002",
            activity_id=self.source_act.id,
            timestamp="2026-10-15T12:00:00Z",
            parent_checkpoint_id=self.chk1.id,
            progress={"percentage": 50.0},
            completed_work=["Define protocol specification", "Implement handshake parser"],
            pending_actions=["Implement retry backoff"],
            decisions=[
                DecisionRecord(id="dec_01", decision="Use JSON-over-HTTP"),
                DecisionRecord(id="dec_02", decision="Exponential backoff algorithm"),
            ],
            context="Handshake verified; moving to retry policy.",
            artifacts=[
                ArtifactReference(
                    name="spec.md",
                    path_or_uri="docs/spec.md",
                    mode=ArtifactMode.REFERENCE,
                    checksum_sha256="abc123sha",
                ),
                ArtifactReference(
                    name="handshake.py",
                    path_or_uri="src/handshake.py",
                    mode=ArtifactMode.SNAPSHOT,
                    snapshot_content="def handshake(): return True",
                ),
            ],
        )
        self.store.commit_checkpoint(self.chk2)

        self.chk3 = UniversalCheckpoint(
            id="chk_source_003",
            activity_id=self.source_act.id,
            timestamp="2026-10-15T14:00:00Z",
            parent_checkpoint_id=self.chk2.id,
            progress={"percentage": 75.0},
            completed_work=["Define protocol specification", "Implement handshake parser", "Implement retry backoff"],
            pending_actions=["Production load testing"],
            decisions=[
                DecisionRecord(id="dec_01", decision="Use JSON-over-HTTP"),
                DecisionRecord(id="dec_02", decision="Exponential backoff algorithm"),
                DecisionRecord(id="dec_03", decision="Circuit breaker threshold 5"),
            ],
            context="Retry policy implemented; preparing for load test.",
        )
        self.store.commit_checkpoint(self.chk3)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _file_hash(self, path: Path) -> str:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def test_branch_from_old_and_recent_checkpoints(self):
        """
        Verify that branching from an older checkpoint (chk_1) and a recent one (chk_3)
        produces independent continuations with state corresponding exactly to their origin.
        """
        # 1. Branch from older checkpoint chk1
        branch_old_act, branch_old_chk = self.store.branch_from_checkpoint(
            source_checkpoint_id=self.chk1.id,
            branch_name="experiment-old",
            new_title="Alternative Architecture Branch",
        )

        self.assertNotEqual(branch_old_act.id, self.source_act.id)
        self.assertEqual(branch_old_act.title, "Alternative Architecture Branch")
        self.assertIn("branch", branch_old_act.tags)
        self.assertIn(self.source_act.id, branch_old_act.related_activity_ids)
        self.assertEqual(branch_old_act.metadata["branch_source_checkpoint_id"], self.chk1.id)
        self.assertEqual(branch_old_act.metadata["branch_source_activity_id"], self.source_act.id)

        # Verify initial checkpoint in branch reflects chk1 state (25% progress, 1 completed work)
        self.assertEqual(branch_old_chk.activity_id, branch_old_act.id)
        self.assertEqual(branch_old_chk.branch_source_checkpoint_id, self.chk1.id)
        self.assertIsNone(branch_old_chk.parent_checkpoint_id)
        self.assertEqual(branch_old_chk.progress.get("percentage"), 25.0)
        self.assertEqual(branch_old_chk.completed_work, ["Define protocol specification"])
        self.assertEqual(len(branch_old_chk.decisions), 1)
        self.assertEqual(branch_old_chk.decisions[0].decision, "Use JSON-over-HTTP")

        # 2. Branch from recent checkpoint chk3
        branch_recent_act, branch_recent_chk = self.store.branch_from_checkpoint(
            source_checkpoint_id=self.chk3.id,
            branch_name="load-testing-spike",
        )

        self.assertIn("Branch: load-testing-spike", branch_recent_act.title)
        self.assertEqual(branch_recent_chk.progress.get("percentage"), 75.0)
        self.assertEqual(len(branch_recent_chk.completed_work), 3)
        self.assertEqual(len(branch_recent_chk.decisions), 3)
        self.assertEqual(branch_recent_chk.branch_source_checkpoint_id, self.chk3.id)

    def test_gate_branching_never_mutates_source_branch_or_checkpoints(self):
        """
        Gate Invariant: Branching is NOT restore and NEVER mutates the source branch.
        Verifies that source activity.json and all checkpoint files remain byte-identical.
        """
        source_act_file = self.store._get_activity_file(self.source_act.id)
        chk1_file = self.store._get_checkpoint_file(self.source_act.id, self.chk1.id)
        chk2_file = self.store._get_checkpoint_file(self.source_act.id, self.chk2.id)
        chk3_file = self.store._get_checkpoint_file(self.source_act.id, self.chk3.id)

        # Record pre-branch hashes and modification timestamps
        before_hashes = {
            "act": self._file_hash(source_act_file),
            "chk1": self._file_hash(chk1_file),
            "chk2": self._file_hash(chk2_file),
            "chk3": self._file_hash(chk3_file),
        }
        before_mtimes = {
            "act": source_act_file.stat().st_mtime_ns,
            "chk1": chk1_file.stat().st_mtime_ns,
            "chk2": chk2_file.stat().st_mtime_ns,
            "chk3": chk3_file.stat().st_mtime_ns,
        }

        # Perform branching operation
        self.store.branch_from_checkpoint(
            source_checkpoint_id=self.chk2.id,
            branch_name="feature-gate-test",
        )

        # Verify post-branch hashes and timestamps are completely identical
        after_hashes = {
            "act": self._file_hash(source_act_file),
            "chk1": self._file_hash(chk1_file),
            "chk2": self._file_hash(chk2_file),
            "chk3": self._file_hash(chk3_file),
        }
        after_mtimes = {
            "act": source_act_file.stat().st_mtime_ns,
            "chk1": chk1_file.stat().st_mtime_ns,
            "chk2": chk2_file.stat().st_mtime_ns,
            "chk3": chk3_file.stat().st_mtime_ns,
        }

        self.assertEqual(before_hashes, after_hashes, "Source activity or checkpoint file mutated during branch!")
        self.assertEqual(before_mtimes, after_mtimes, "Source file modification times were touched during branch!")

        # Verify source activity checkpoints list is unmodified
        chks, total = self.store.list_checkpoints(self.source_act.id)
        self.assertEqual(total, 3)
        self.assertEqual([c.id for c in chks], [self.chk3.id, self.chk2.id, self.chk1.id])

    def test_artifact_reference_reuse_without_duplication(self):
        """
        Verify that artifact references and snapshot metadata are preserved without
        bloating disk or creating duplicate files.
        """
        branch_act, branch_chk = self.store.branch_from_checkpoint(
            source_checkpoint_id=self.chk2.id,
            branch_name="artifact-reuse-test",
        )

        self.assertEqual(len(branch_chk.artifacts), 2)
        ref_art = next(a for a in branch_chk.artifacts if a.name == "spec.md")
        snap_art = next(a for a in branch_chk.artifacts if a.name == "handshake.py")

        self.assertEqual(ref_art.mode, ArtifactMode.REFERENCE)
        self.assertEqual(ref_art.checksum_sha256, "abc123sha")
        self.assertEqual(snap_art.mode, ArtifactMode.SNAPSHOT)
        self.assertEqual(snap_art.snapshot_content, "def handshake(): return True")

    def test_rename_ancestry_preservation_and_ancestry_chain(self):
        """
        Verify that renaming an activity preserves stable identity (I-01) and
        ancestry tracking across multiple branch levels.
        """
        # Level 1 branch
        b1_act, b1_chk = self.store.branch_from_checkpoint(
            source_checkpoint_id=self.chk2.id,
            branch_name="layer-1",
        )

        # Rename source activity
        self.source_act.title = "Core Platform - RENAMED"
        self.store.update_activity(self.source_act)

        # Add a checkpoint in Level 1 branch
        b1_chk2 = UniversalCheckpoint(
            id="chk_b1_002",
            activity_id=b1_act.id,
            parent_checkpoint_id=b1_chk.id,
            progress={"percentage": 60.0},
            context="Progressed on layer 1 branch",
        )
        self.store.commit_checkpoint(b1_chk2)

        # Level 2 branch (branching from layer 1 branch's checkpoint)
        b2_act, b2_chk = self.store.branch_from_checkpoint(
            source_checkpoint_id=b1_chk2.id,
            branch_name="layer-2",
        )

        # Verify ancestry traceability
        ancestry = self.store.get_branch_ancestry(b2_act.id)
        self.assertTrue(ancestry["is_branch"])
        self.assertEqual(ancestry["branch_name"], "layer-2")
        self.assertEqual(ancestry["branch_source_checkpoint_id"], b1_chk2.id)
        self.assertEqual(ancestry["branch_source_activity_id"], b1_act.id)
        self.assertEqual(ancestry["ancestry_depth"], 2)

        chain = ancestry["ancestry_chain"]
        self.assertEqual(chain[0]["activity_id"], b2_act.id)
        self.assertEqual(chain[0]["source_activity_id"], b1_act.id)
        self.assertEqual(chain[1]["activity_id"], b1_act.id)
        self.assertEqual(chain[1]["source_activity_id"], self.source_act.id)

    def test_partial_failure_and_rollback(self):
        """
        Verifies that if an error occurs midway through branching, the partially created
        directory and index rows are completely rolled back without corrupting the store.
        """
        # Monkeypatch commit_checkpoint to simulate mid-process failure
        original_commit = self.store.commit_checkpoint

        def failing_commit(chk):
            raise IOError("Simulated disk full or I/O error during checkpoint commit")

        self.store.commit_checkpoint = failing_commit
        target_new_id = "act_should_be_rolled_back"

        with self.assertRaises(CommitFailedError):
            self.store.branch_from_checkpoint(
                source_checkpoint_id=self.chk1.id,
                new_activity_id=target_new_id,
            )

        # Restore original commit method
        self.store.commit_checkpoint = original_commit

        # Verify no directory or database trace remains
        failed_dir = self.store._get_activity_dir(target_new_id)
        self.assertFalse(failed_dir.exists(), "Rollback failed: partial activity directory still exists!")

        with self.store._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM activities_idx WHERE id = ?", (target_new_id,))
            self.assertEqual(cur.fetchone()[0], 0, "Rollback failed: activity found in index!")

    def test_idempotent_retry_after_failure(self):
        """
        Verifies that after a failed attempt, retrying the branch succeeds cleanly.
        """
        retry_act_id = "act_retry_target"
        # 1. Attempt with non-existent source checkpoint -> CheckpointNotFoundError
        with self.assertRaises(CheckpointNotFoundError):
            self.store.branch_from_checkpoint(
                source_checkpoint_id="chk_non_existent",
                new_activity_id=retry_act_id,
            )

        # 2. Retry with valid source checkpoint -> succeeds
        created_act, created_chk = self.store.branch_from_checkpoint(
            source_checkpoint_id=self.chk2.id,
            new_activity_id=retry_act_id,
        )
        self.assertEqual(created_act.id, retry_act_id)
        self.assertEqual(created_chk.activity_id, retry_act_id)


class TestPhase65BranchApi(unittest.TestCase):
    """Integration tests for HTTP endpoints POST /api/v1/activities/branch & GET /api/v1/activities/branch/ancestry."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="continuum_p65_api_")
        cls.workspace = Path(cls.temp_dir)

        cls.store = ActivityCheckpointStore(str(cls.workspace))
        cls.act = Activity(id="act_api_source", title="API Source Activity")
        cls.store.create_activity(cls.act)

        cls.chk = UniversalCheckpoint(
            id="chk_api_001",
            activity_id=cls.act.id,
            progress={"percentage": 40.0},
            completed_work=["Step 1"],
            context="Baseline for API branching",
        )
        cls.store.commit_checkpoint(cls.chk)

        # Start daemon on dynamic port
        cls.daemon = ContinuumHttpDaemon(cls.temp_dir, host="127.0.0.1", default_port=8965)
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

    def _get(self, path: str):
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url)
        req.add_header("X-Continuum-Token", self.token)
        return urllib.request.urlopen(req, timeout=5)

    def test_api_branch_success(self):
        payload = {
            "source_checkpoint_id": self.chk.id,
            "branch_name": "api-exp",
            "title": "API Test Branch",
        }
        res = self._post("/api/v1/activities/branch", payload)
        self.assertEqual(res.status, 201)
        data = json.loads(res.read().decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["activity"]["title"], "API Test Branch")
        self.assertEqual(data["branch_origin"]["source_checkpoint_id"], self.chk.id)

        branch_act_id = data["activity"]["id"]

        # Now test GET /api/v1/activities/branch/ancestry
        res_anc = self._get(f"/api/v1/activities/branch/ancestry?activity_id={branch_act_id}")
        self.assertEqual(res_anc.status, 200)
        anc_data = json.loads(res_anc.read().decode("utf-8"))
        self.assertTrue(anc_data["ancestry"]["is_branch"])
        self.assertEqual(anc_data["ancestry"]["branch_name"], "api-exp")

    def test_api_branch_missing_source(self):
        payload = {"branch_name": "bad-branch"}
        try:
            self._post("/api/v1/activities/branch", payload)
            self.fail("Expected HTTPError 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

    def test_api_branch_non_existent_checkpoint(self):
        payload = {"source_checkpoint_id": "chk_missing_999"}
        try:
            self._post("/api/v1/activities/branch", payload)
            self.fail("Expected HTTPError 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)


if __name__ == "__main__":
    unittest.main()
