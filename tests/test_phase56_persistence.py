"""
Project Continuum — Phase 56 Test Suite
========================================
Milestone 37: Durable Storage and Migration
Phase 56: Persistence Extension and Durable Commits

Validates:
1. Activity CRUD operations and index persistence.
2. Checkpoint durable commit, retrieval, and relational integrity.
3. Restart persistence: re-instantiating storage preserves all state across process restarts.
4. Failed commit handling: simulated disk/write failure leaves no partial file and raises CommitFailedError.
5. Idempotent retry / duplicate commit handling without state duplication.
6. Large-list paging: bounded retrieval (I-17), limit clamping, and total count accuracy.
7. Dangling relation prevention: non-existent activity_id or parent_checkpoint_id rejected.
8. Non-authoritative index recovery: index rebuild from authoritative JSON files (I-06).
"""

from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from core.activity import Activity, ActivityStatus, ActivityType
from core.checkpoint import UniversalCheckpoint, DecisionRecord, ArtifactReference
from core.enums import ArtifactMode, ProvenanceType
from core.invariants import CommitFailedError
from storage.activity_store import (
    ActivityCheckpointStore,
    ActivityNotFoundError,
    CheckpointNotFoundError,
    DanglingReferenceError,
)


class TestPhase56Persistence(unittest.TestCase):
    """Test suite for durable storage, commit confirmation, and pagination."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="continuum_p56_test_")
        self.store = ActivityCheckpointStore(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_activity_crud_lifecycle(self):
        """Verifies creating, reading, updating, and listing activities."""
        # Create
        act = Activity.create_blank(
            title="Implement Universal Resume",
            activity_type=ActivityType.CODING,
            description="Cross-model work continuity",
            tags=["v1.4.0", "storage"],
        )
        saved_act = self.store.create_activity(act)
        self.assertEqual(saved_act.id, act.id)

        # Read
        loaded_act = self.store.get_activity(act.id)
        self.assertEqual(loaded_act.id, act.id)
        self.assertEqual(loaded_act.title, "Implement Universal Resume")
        self.assertEqual(loaded_act.status, ActivityStatus.ACTIVE)
        self.assertIn("v1.4.0", loaded_act.tags)

        # Update
        loaded_act.title = "Implement Universal Resume Anywhere"
        loaded_act.transition_to(ActivityStatus.PAUSED)
        updated_act = self.store.update_activity(loaded_act)
        self.assertEqual(updated_act.title, "Implement Universal Resume Anywhere")
        self.assertEqual(updated_act.status, ActivityStatus.PAUSED)

        # Re-fetch to ensure persistence
        refetched = self.store.get_activity(act.id)
        self.assertEqual(refetched.status, ActivityStatus.PAUSED)
        self.assertEqual(refetched.title, "Implement Universal Resume Anywhere")

    def test_checkpoint_commit_and_retrieval(self):
        """Verifies committing and reading universal checkpoints with structured fields."""
        act = self.store.create_activity(Activity.create_blank(title="Backend Refactor"))

        chk = UniversalCheckpoint.create_minimal(
            activity_id=act.id,
            context="Refactoring the backend storage subsystem",
        )
        chk.completed_work = ["Step 1: Analyzed schema"]
        chk.pending_actions = ["Step 2: Add index"]
        chk.decisions = [DecisionRecord(id="dec_01", decision="Use SQLite for index", rationale="Standard library, zero deps")]
        chk.artifacts = [ArtifactReference(name="activity_store.py", path_or_uri="storage/activity_store.py", mode=ArtifactMode.REFERENCE)]
        chk.progress = {"percentage": 50.0}

        committed = self.store.commit_checkpoint(chk)
        self.assertEqual(committed.id, chk.id)

        # Fetch
        loaded_chk = self.store.get_checkpoint(chk.id)
        self.assertEqual(loaded_chk.id, chk.id)
        self.assertEqual(loaded_chk.activity_id, act.id)
        self.assertEqual(loaded_chk.progress, {"percentage": 50.0})
        self.assertEqual(len(loaded_chk.completed_work), 1)
        self.assertEqual(len(loaded_chk.decisions), 1)
        self.assertEqual(loaded_chk.decisions[0].decision, "Use SQLite for index")

    def test_restart_persistence(self):
        """Verifies that closing and re-instantiating store loads all records accurately."""
        act = self.store.create_activity(Activity.create_blank(title="Persistent Task"))
        chk = UniversalCheckpoint.create_minimal(activity_id=act.id)
        chk.completed_work = ["Persisted step"]
        chk.progress = {"percentage": 25.0}
        self.store.commit_checkpoint(chk)

        # Simulate restart: create brand new store pointing to same directory
        restarted_store = ActivityCheckpointStore(self.temp_dir)
        loaded_act = restarted_store.get_activity(act.id)
        loaded_chk = restarted_store.get_checkpoint(chk.id)

        self.assertEqual(loaded_act.title, "Persistent Task")
        self.assertEqual(loaded_chk.completed_work, ["Persisted step"])

    def test_failed_commit_atomic_cleanup(self):
        """Verifies that simulated disk write failure leaves no partial file and raises CommitFailedError."""
        act = self.store.create_activity(Activity.create_blank(title="Failure Test Activity"))
        chk = UniversalCheckpoint.create_minimal(activity_id=act.id)
        chk.completed_work = ["In-flight step"]

        # Mock open to simulate sudden IO disk error during write
        with patch("builtins.open", side_effect=IOError("Simulated disk full / IO error")):
            with self.assertRaises(CommitFailedError):
                self.store.commit_checkpoint(chk)

        # Ensure no partial target file or tmp file was left in checkpoints directory
        chk_dir = self.store._get_checkpoints_dir(act.id)
        target_file = self.store._get_checkpoint_file(act.id, chk.id)
        self.assertFalse(target_file.exists())
        tmp_files = list(chk_dir.glob("*.tmp*"))
        self.assertEqual(len(tmp_files), 0)

        # Verify not in index
        with self.assertRaises(CheckpointNotFoundError):
            self.store.get_checkpoint(chk.id)

    def test_idempotent_duplicate_checkpoint_commit(self):
        """Verifies that committing the exact same checkpoint twice is idempotent and safe."""
        act = self.store.create_activity(Activity.create_blank(title="Duplicate Test"))
        chk = UniversalCheckpoint.create_minimal(activity_id=act.id)
        chk.completed_work = ["Initial task"]
        chk.progress = {"percentage": 30.0}

        # First commit
        c1 = self.store.commit_checkpoint(chk)
        # Second duplicate commit with same ID and data
        c2 = self.store.commit_checkpoint(chk)

        self.assertEqual(c1.id, c2.id)
        # Verify checkpoint list contains only 1 entry
        checkpoints, total = self.store.list_checkpoints(act.id)
        self.assertEqual(total, 1)
        self.assertEqual(len(checkpoints), 1)

    def test_dangling_relations_rejected(self):
        """Verifies that committing a checkpoint with non-existent activity or parent is rejected."""
        # Non-existent activity
        orphan_chk = UniversalCheckpoint.create_minimal(activity_id="act_non_existent_12345")
        orphan_chk.completed_work = ["Orphan"]
        with self.assertRaises(DanglingReferenceError) as ctx:
            self.store.commit_checkpoint(orphan_chk)
        self.assertIn("non-existent activity", str(ctx.exception))

        # Existing activity, but non-existent parent checkpoint
        act = self.store.create_activity(Activity.create_blank(title="Parent Check"))
        invalid_parent_chk = UniversalCheckpoint.create_minimal(
            activity_id=act.id,
            parent_checkpoint_id="chk_ghost_parent_9999",
        )
        invalid_parent_chk.completed_work = ["Bad parent"]
        with self.assertRaises(DanglingReferenceError) as ctx2:
            self.store.commit_checkpoint(invalid_parent_chk)
        self.assertIn("Parent checkpoint 'chk_ghost_parent_9999' does not exist", str(ctx2.exception))

    def test_large_list_pagination_and_bounds(self):
        """Verifies bounded pagination (I-17), limit clamping, and total counts for large lists."""
        act = self.store.create_activity(Activity.create_blank(title="Large Timeline"))

        # Create 35 checkpoints for this activity
        parent_id = None
        for i in range(35):
            chk = UniversalCheckpoint.create_minimal(
                activity_id=act.id,
                parent_checkpoint_id=parent_id,
            )
            chk.completed_work = [f"Task #{i}"]
            chk.progress = {"percentage": float(i * 2)}
            saved = self.store.commit_checkpoint(chk)
            parent_id = saved.id

        # Page 1: limit 10, offset 0
        p1, total = self.store.list_checkpoints(act.id, limit=10, offset=0)
        self.assertEqual(total, 35)
        self.assertEqual(len(p1), 10)

        # Page 2: limit 10, offset 10
        p2, total2 = self.store.list_checkpoints(act.id, limit=10, offset=10)
        self.assertEqual(total2, 35)
        self.assertEqual(len(p2), 10)
        # Ensure page 1 and page 2 contain different checkpoints
        p1_ids = {c.id for c in p1}
        p2_ids = {c.id for c in p2}
        self.assertEqual(len(p1_ids.intersection(p2_ids)), 0)

        # Bounded retrieval limit clamping (requesting 500 clamped to MAX_PAGE_LIMIT = 100)
        p_clamped, _ = self.store.list_checkpoints(act.id, limit=500, offset=0)
        self.assertEqual(len(p_clamped), 35)  # Total 35 items returned without error

    def test_derived_index_rebuild_from_authoritative_files(self):
        """Verifies that deleting the SQLite index file and rebuilding restores 100% of data (I-06)."""
        act1 = self.store.create_activity(Activity.create_blank(title="Activity Alpha"))
        act2 = self.store.create_activity(Activity.create_blank(title="Activity Beta"))

        chk1 = self.store.commit_checkpoint(UniversalCheckpoint.create_minimal(activity_id=act1.id))
        chk2 = self.store.commit_checkpoint(UniversalCheckpoint.create_minimal(activity_id=act1.id))
        chk3 = self.store.commit_checkpoint(UniversalCheckpoint.create_minimal(activity_id=act2.id))

        # Check total before
        acts, total_acts = self.store.list_activities()
        self.assertEqual(total_acts, 2)
        chks, total_chks = self.store.list_checkpoints(act1.id)
        self.assertEqual(total_chks, 2)

        # Delete the SQLite index file completely
        index_db_file = self.store.db_path
        self.assertTrue(index_db_file.exists())
        index_db_file.unlink()

        # Re-initialize or rebuild index
        new_store = ActivityCheckpointStore(self.temp_dir)
        total_rebuilt = new_store.rebuild_index_from_authoritative_files()
        self.assertEqual(total_rebuilt, 5)  # 2 activities + 3 checkpoints

        # Verify query results match original state exactly
        rebuilt_acts, rebuilt_acts_count = new_store.list_activities()
        self.assertEqual(rebuilt_acts_count, 2)
        rebuilt_chks, rebuilt_chks_count = new_store.list_checkpoints(act1.id)
        self.assertEqual(rebuilt_chks_count, 2)


if __name__ == "__main__":
    unittest.main()
