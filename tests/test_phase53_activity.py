"""
Project Continuum - Phase 53 Activity & Lifecycle Model Test Suite
==================================================================
Milestone 36: Domain Model and Invariants
Phase 53: Activity and Lifecycle Model

Tests Activity identity, templates, custom types, lifecycle state machine,
reopening completed activities, archived recovery, and stable IDs.
"""

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.enums import ActivityStatus, ActivityType
from core.activity import (
    Activity,
    ActivityValidationError,
    InvalidStatusTransitionError,
    VALID_STATUS_TRANSITIONS,
    ACTIVITY_TEMPLATES,
)


class TestPhase53ActivityLifecycle(unittest.TestCase):
    """Verifies all functional contracts and invariants of the Activity domain model."""

    def test_activity_blank_creation_and_defaults(self):
        """Verify blank activity instantiation with stable ID and valid default fields."""
        act = Activity.create_blank(title="Initial Exploration")
        self.assertTrue(act.id.startswith("act_"))
        self.assertEqual(act.title, "Initial Exploration")
        self.assertEqual(act.activity_type, ActivityType.CODING.value)
        self.assertEqual(act.status, ActivityStatus.ACTIVE)
        self.assertEqual(act.tags, [])
        self.assertIsNone(act.collection)
        self.assertIsNotNone(act.created_at)
        self.assertIsNotNone(act.updated_at)
        self.assertEqual(act.related_activity_ids, [])

    def test_activity_validation_errors(self):
        """Verify validation rejects empty IDs, empty titles, or invalid status names."""
        with self.assertRaises(ActivityValidationError):
            Activity(id="", title="Valid Title")
        
        with self.assertRaises(ActivityValidationError):
            Activity(id="act_123", title="   ")
            
        with self.assertRaises(ActivityValidationError):
            Activity(id="act_123", title="Valid Title", status="non_existent_status")

    def test_stable_id_across_edits_and_renames(self):
        """Verify updating title, description, tags, and collection preserves immutable ID (I-01)."""
        act = Activity.create_blank(title="Draft Design", custom_id="act_stable_001")
        orig_id = act.id
        orig_updated_at = act.updated_at

        # Rename and update metadata
        act.update_details(
            title="Refined Production Architecture",
            description="Detailed microservice specification.",
            tags=["Arch", "SPEC", "arch"],  # Should be normalized and deduplicated
            collection="Continuum Core",
            activity_type=ActivityType.RESEARCH
        )

        self.assertEqual(act.id, orig_id, "Activity ID must never change upon rename or edit")
        self.assertEqual(act.title, "Refined Production Architecture")
        self.assertEqual(act.description, "Detailed microservice specification.")
        self.assertEqual(act.tags, ["arch", "spec"], "Tags should be deduplicated and lowercased")
        self.assertEqual(act.collection, "Continuum Core")
        self.assertEqual(act.activity_type, ActivityType.RESEARCH.value)
        self.assertGreaterEqual(act.updated_at, orig_updated_at)

    def test_built_in_templates_instantiation(self):
        """Verify creation from all built-in templates (Coding, Study, Research, Writing, Work Task, AI Agent)."""
        templates = [
            ActivityType.CODING,
            ActivityType.STUDY,
            ActivityType.RESEARCH,
            ActivityType.WRITING,
            ActivityType.WORK_TASK,
            ActivityType.AI_AGENT
        ]
        for tpl in templates:
            act = Activity.create_from_template(tpl)
            self.assertEqual(act.activity_type, tpl.value)
            self.assertEqual(act.status, ActivityStatus.ACTIVE)
            self.assertFalse(act.is_custom_type)
            self.assertGreater(len(act.tags), 0)
            self.assertIn("template_steps", act.metadata)
            self.assertGreater(len(act.metadata["template_steps"]), 0)

    def test_custom_activity_type(self):
        """Verify custom domain types are seamlessly supported and identified."""
        act = Activity.create_blank(
            title="Financial Audit Q4",
            activity_type="financial_audit",
            tags=["finance", "audit"]
        )
        self.assertEqual(act.activity_type, "financial_audit")
        self.assertTrue(act.is_custom_type)
        self.assertIn("finance", act.tags)

    def test_valid_lifecycle_transitions(self):
        """Verify permitted status transitions: active <-> paused, active -> completed, etc."""
        act = Activity.create_blank(title="Lifecycle Test")
        self.assertEqual(act.status, ActivityStatus.ACTIVE)

        # active -> paused
        act.pause()
        self.assertEqual(act.status, ActivityStatus.PAUSED)

        # paused -> active
        act.resume()
        self.assertEqual(act.status, ActivityStatus.ACTIVE)

        # active -> completed
        act.complete()
        self.assertEqual(act.status, ActivityStatus.COMPLETED)

        # completed -> active (reopening) (I-16)
        act.reopen()
        self.assertEqual(act.status, ActivityStatus.ACTIVE)

        # active -> archived
        act.archive()
        self.assertEqual(act.status, ActivityStatus.ARCHIVED)

        # archived -> active (restoration)
        act.restore_from_archive(ActivityStatus.ACTIVE)
        self.assertEqual(act.status, ActivityStatus.ACTIVE)

        # active -> paused -> archived -> paused (restore to paused)
        act.pause()
        act.archive()
        act.restore_from_archive(ActivityStatus.PAUSED)
        self.assertEqual(act.status, ActivityStatus.PAUSED)

    def test_invalid_lifecycle_transitions_rejected(self):
        """Verify illegal transitions raise InvalidStatusTransitionError (I-16)."""
        act = Activity.create_blank(title="Illegal Transition Test")
        act.complete()
        self.assertEqual(act.status, ActivityStatus.COMPLETED)

        # completed cannot transition directly to paused without reopening to active first
        with self.assertRaises(InvalidStatusTransitionError):
            act.pause()

        # completed -> archived is valid
        act.archive()
        self.assertEqual(act.status, ActivityStatus.ARCHIVED)

        # archived cannot transition directly to completed
        with self.assertRaises(InvalidStatusTransitionError):
            act.complete()

    def test_related_activity_linking(self):
        """Verify linking related activities does not merge history and deduplicates links."""
        act1 = Activity.create_blank(title="Activity 1", custom_id="act_001")
        act2 = Activity.create_blank(title="Activity 2", custom_id="act_002")

        act1.link_related_activity(act2.id)
        act1.link_related_activity(act2.id)  # duplicate should be ignored
        act1.link_related_activity(act1.id)  # self-link should be ignored
        
        self.assertEqual(act1.related_activity_ids, ["act_002"])

        # Unlink
        act1.unlink_related_activity("act_002")
        self.assertEqual(act1.related_activity_ids, [])

    def test_serialization_round_trip(self):
        """Verify dictionary serialization and deserialization preserves all fields."""
        act = Activity.create_from_template(
            ActivityType.RESEARCH,
            title="Distributed Consensus Research",
            collection="Distributed Systems",
            custom_tags=["raft", "paxos"],
            custom_id="act_consensus_999"
        )
        act.description = "Evaluating Raft vs Multi-Paxos for metadata replication."
        act.link_related_activity("act_storage_101")
        act.pause()

        data = act.to_dict()
        restored = Activity.from_dict(data)

        self.assertEqual(restored.id, "act_consensus_999")
        self.assertEqual(restored.title, "Distributed Consensus Research")
        self.assertEqual(restored.description, "Evaluating Raft vs Multi-Paxos for metadata replication.")
        self.assertEqual(restored.activity_type, ActivityType.RESEARCH.value)
        self.assertEqual(restored.status, ActivityStatus.PAUSED)
        self.assertIn("raft", restored.tags)
        self.assertEqual(restored.collection, "Distributed Systems")
        self.assertEqual(restored.related_activity_ids, ["act_storage_101"])
        self.assertEqual(restored.metadata, act.metadata)


if __name__ == "__main__":
    unittest.main()
