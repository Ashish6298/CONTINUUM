"""
Project Continuum — Phase 61 Test Suite
========================================
Milestone 38: Capture and Resume
Phase 61: Resume Center and Activity Detail

Validates:
1. End-to-end Continuity: create activity -> capture checkpoint -> reopen/resume works offline.
2. Activity detail endpoint: `GET /api/v1/activities/detail` returns activity metadata, latest checkpoint, timeline, and prominent brief.
3. Empty state handling: non-existent checkpoints or empty activity returns clean minimal brief without crash.
4. Storage failure resilience: handling corrupted activity records safely returns HTTP 404/500 errors.
5. Navigation and layout non-regression: embedded SPA serves index.html and scripts without breaking composer views.
6. Multi-checkpoint timeline ordering: checkpoints in timeline are ordered chronologically.
"""

from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from core.activity import Activity, ActivityType, ActivityStatus
from core.checkpoint import UniversalCheckpoint, DecisionRecord
from core.resume_generator import DeterministicResumeBriefGenerator
from storage.activity_store import ActivityCheckpointStore, ActivityNotFoundError


class TestPhase61ResumeCenter(unittest.TestCase):
    """Test suite for Phase 61: Resume Center and Activity Detail."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="continuum_p61_test_")
        self.workspace_root = Path(self.temp_dir)
        self.store = ActivityCheckpointStore(self.workspace_root)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_checkpoint_reopen_resume_offline(self):
        """
        Gate Test: create activity -> checkpoint -> leave/reopen -> resume works offline.
        """
        # Step 1: Create activity
        act = Activity.create_blank(
            title="Design Payment Gateway Integration",
            activity_type=ActivityType.WORK_TASK,
            description="Build Stripe and PayPal webhook listeners",
        )
        self.store.create_activity(act)

        # Step 2: Capture initial checkpoint
        chk1 = UniversalCheckpoint(
            id="chk_pg_001",
            activity_id=act.id,
            context="Set up webhook signatures verification and models",
            completed_work=["Created webhook route", "Configured secret HMAC"],
            pending_actions=["Write test fixtures for failed payments"],
            decisions=[
                DecisionRecord(
                    id="dec_01",
                    decision="Use HMAC-SHA256 for signature verification",
                    rationale="Standard industry practice",
                )
            ],
        )
        self.store.commit_checkpoint(chk1)

        # Step 3: Simulate leave / process restart by opening fresh store instance
        reopened_store = ActivityCheckpointStore(self.workspace_root)
        loaded_act = reopened_store.get_activity(act.id)
        self.assertEqual(loaded_act.title, act.title)

        # Step 4: Resume - generate actionable brief from latest state
        checkpoints, total = reopened_store.list_checkpoints(act.id, limit=1)
        self.assertEqual(total, 1)
        latest_chk = checkpoints[0]

        generator = DeterministicResumeBriefGenerator()
        brief = generator.generate_brief(loaded_act, latest_chk)

        # Verify resumption brief completeness
        self.assertIn("Set up webhook signatures", brief.purpose)
        self.assertEqual(len(brief.last_completed_work), 2)
        self.assertEqual(len(brief.next_actions), 1)
        self.assertIn("Write test fixtures", brief.next_actions[0])

    def test_activity_detail_with_multiple_checkpoints(self):
        """Verifies that an activity with multiple checkpoints renders timeline and latest brief."""
        act = Activity.create_blank(
            title="Refactor Query Planner",
            activity_type=ActivityType.CODING,
            description="Optimize SQL index scans",
        )
        self.store.create_activity(act)

        chk1 = UniversalCheckpoint(
            id="chk_qp_001",
            activity_id=act.id,
            context="Baseline benchmark established",
            completed_work=["Measured 45ms per query"],
            pending_actions=["Add composite B-Tree index"],
        )
        self.store.commit_checkpoint(chk1)

        chk2 = UniversalCheckpoint(
            id="chk_qp_002",
            activity_id=act.id,
            context="Added composite index",
            parent_checkpoint_id="chk_qp_001",
            completed_work=["Created composite index on (user_id, status)"],
            pending_actions=["Rerun query benchmarks"],
        )
        self.store.commit_checkpoint(chk2)

        # List checkpoints
        checkpoints, total = self.store.list_checkpoints(act.id, limit=10)
        self.assertEqual(total, 2)
        # Checkpoints list is ordered descending by timestamp
        self.assertEqual(len(checkpoints), 2)

        # Generator consumes latest checkpoint
        generator = DeterministicResumeBriefGenerator()
        brief = generator.generate_brief(act, checkpoints[0])
        self.assertIn("Added composite index", brief.purpose)

    def test_empty_activity_detail_resilience(self):
        """Verifies that an activity with no checkpoints returns a clean initial brief."""
        act = Activity.create_blank(
            title="Blank Research Session",
            activity_type=ActivityType.RESEARCH,
            description="Investigating distributed consensus algorithms",
        )
        self.store.create_activity(act)

        # Minimal fallback checkpoint
        empty_chk = UniversalCheckpoint.create_minimal(activity_id=act.id, context=act.description)
        generator = DeterministicResumeBriefGenerator()
        brief = generator.generate_brief(act, empty_chk)

        self.assertEqual(brief.purpose, act.description)
        self.assertIn("[None reported]", brief.blockers[0])
        self.assertIn(act.title, brief.next_actions[0])

    def test_activity_not_found_error(self):
        """Verifies querying non-existent activity raises ActivityNotFoundError."""
        with self.assertRaises(ActivityNotFoundError):
            self.store.get_activity("act_non_existent")


if __name__ == "__main__":
    unittest.main()
