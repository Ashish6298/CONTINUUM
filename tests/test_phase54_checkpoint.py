"""
Project Continuum - Phase 54 Checkpoint & Provenance Model Test Suite
====================================================================
Milestone 36: Domain Model and Invariants
Phase 54: Checkpoint and Provenance Model

Tests Checkpoint creation, minimal vs full serialization, absent optional fields,
provenance classifications, artifact references vs snapshots, legacy compatibility,
and authoritative vs derived field boundaries.
"""

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.enums import ArtifactMode, ProvenanceType
from core.checkpoint import (
    UniversalCheckpoint,
    CheckpointValidationError,
    ProvenanceRecord,
    DecisionRecord,
    ArtifactReference,
    ResumeBrief,
)
from core.state_models import HandoffCheckpoint


class TestPhase54CheckpointProvenance(unittest.TestCase):
    """Verifies all functional contracts and invariants of the Checkpoint domain model."""

    def test_minimal_checkpoint_creation_and_defaults(self):
        """Verify minimal checkpoint creation where all optional fields default safely (I-18)."""
        cp = UniversalCheckpoint.create_minimal(activity_id="act_main_01")
        self.assertTrue(cp.id.startswith("chk_"))
        self.assertEqual(cp.activity_id, "act_main_01")
        self.assertIsNotNone(cp.timestamp)
        self.assertIsNone(cp.parent_checkpoint_id)
        self.assertIsNone(cp.branch_source_checkpoint_id)
        self.assertEqual(cp.structured_state, {})
        self.assertEqual(cp.progress, {})
        self.assertEqual(cp.completed_work, [])
        self.assertEqual(cp.pending_actions, [])
        self.assertEqual(cp.decisions, [])
        self.assertEqual(cp.context, "")
        self.assertEqual(cp.references, [])
        self.assertEqual(cp.blockers, [])
        self.assertEqual(cp.artifacts, [])
        self.assertEqual(cp.permitted_excerpts, [])
        self.assertEqual(cp.provenance.provenance_type, ProvenanceType.USER_CONFIRMED)
        self.assertTrue(cp.provenance.is_authoritative)
        self.assertIsNone(cp.resume_brief)
        self.assertEqual(cp.metadata, {})

    def test_checkpoint_validation_errors(self):
        """Verify validation errors on empty IDs or empty activity_ids."""
        with self.assertRaises(CheckpointValidationError):
            UniversalCheckpoint(id="", activity_id="act_123")

        with self.assertRaises(CheckpointValidationError):
            UniversalCheckpoint(id="chk_123", activity_id="   ")

    def test_full_checkpoint_creation_and_authoritative_fields(self):
        """Verify full checkpoint creation containing decisions, artifacts, and provenance."""
        decision = DecisionRecord(
            id="dec_001",
            decision="Adopt SQLite WAL mode for local index persistence",
            rationale="Eliminates writer contention and ensures crash-safe transactions",
            constraints=["Must run offline without third-party C-bindings", "Pure python compatibility"]
        )

        artifact_ref = ArtifactReference(
            name="schema.py",
            path_or_uri="core/schema.py",
            mode=ArtifactMode.REFERENCE
        )

        artifact_snap = ArtifactReference(
            name="critical_fix.patch",
            path_or_uri="patches/fix.diff",
            mode=ArtifactMode.SNAPSHOT,
            snapshot_content="--- a/server/routes.py\n+++ b/server/routes.py\n@@ ... @@",
            checksum_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            size_bytes=64
        )

        provenance = ProvenanceRecord(
            provenance_type=ProvenanceType.USER_CONFIRMED,
            captured_by="developer_alice",
            is_authoritative=True,
            details={"git_branch": "main", "verified_by_test": True}
        )

        brief = ResumeBrief(
            purpose="Build Checkpoint and Provenance domain model for v1.4.0",
            last_completed_work=["Created core/checkpoint.py", "Added ProvenanceRecord"],
            key_decisions=["WAL mode for local storage"],
            blockers=[],
            unresolved_questions=[],
            next_actions=["Implement storage manager integration in Phase 55"]
        )

        cp = UniversalCheckpoint(
            id="chk_full_001",
            activity_id="act_engine_dev",
            parent_checkpoint_id="chk_root_000",
            structured_state={"files_count": 128, "ast_symbols_count": 650},
            progress={"percentage": 85, "milestone": "Milestone 36"},
            completed_work=["Completed Phase 53 Activity model", "Designed Phase 54 Checkpoint model"],
            pending_actions=["Implement Phase 55 Invariants matrix"],
            decisions=[decision],
            context="Stabilizing domain layer before durable storage updates.",
            references=["docs/ARCHITECTURE.md", "https://project-continuum.dev"],
            blockers=["Pending final user sign-off"],
            artifacts=[artifact_ref, artifact_snap],
            permitted_excerpts=["User: 'Ensure summaries are not authoritative'"],
            provenance=provenance,
            resume_brief=brief,
            metadata={"priority": "high"}
        )

        self.assertEqual(cp.id, "chk_full_001")
        self.assertEqual(len(cp.decisions), 1)
        self.assertEqual(cp.decisions[0].decision, "Adopt SQLite WAL mode for local index persistence")
        self.assertEqual(len(cp.artifacts), 2)
        self.assertEqual(cp.artifacts[0].mode, ArtifactMode.REFERENCE)
        self.assertEqual(cp.artifacts[1].mode, ArtifactMode.SNAPSHOT)
        self.assertIsNotNone(cp.artifacts[1].checksum_sha256)
        self.assertTrue(cp.provenance.is_authoritative)
        self.assertIsNotNone(cp.resume_brief)
        self.assertFalse(cp.resume_brief.is_ai_enhanced)

    def test_provenance_distinction_and_authority(self):
        """Verify provenance distinguishes user-confirmed vs AI-generated or imported content (I-06)."""
        # User confirmed (Authoritative)
        p_user = ProvenanceRecord(provenance_type=ProvenanceType.USER_CONFIRMED, captured_by="user")
        self.assertTrue(p_user.is_authoritative)

        # AI Generated (Non-authoritative interpretation)
        p_ai = ProvenanceRecord(
            provenance_type=ProvenanceType.AI_GENERATED,
            captured_by="claude-3-5-sonnet",
            is_authoritative=False,
            details={"confidence": 0.88}
        )
        self.assertFalse(p_ai.is_authoritative)

        # Auto captured from daemon
        p_auto = ProvenanceRecord(
            provenance_type=ProvenanceType.AUTO_CAPTURED,
            captured_by="daemon_watcher",
            is_authoritative=False
        )
        self.assertFalse(p_auto.is_authoritative)

    def test_legacy_handoff_checkpoint_compatibility(self):
        """Verify seamless backward compatibility with legacy HandoffCheckpoint records (I-18)."""
        legacy = HandoffCheckpoint(
            checkpoint_id="legacy_chk_42",
            origin_model="chatgpt",
            target_model="claude",
            timestamp="2026-10-15T18:30:00Z",
            prompt_summary="Migrated auth middleware to bearer tokens",
            compressed_prompt="<context>Token verified</context>",
            total_messages=12,
            total_code_blocks=4,
            parent_checkpoint_id="legacy_chk_41",
            metadata={"session": "dev_session_1"}
        )

        universal = UniversalCheckpoint.from_legacy_handoff_checkpoint(legacy, activity_id="act_legacy_conv")
        
        self.assertEqual(universal.id, "legacy_chk_42")
        self.assertEqual(universal.activity_id, "act_legacy_conv")
        self.assertEqual(universal.parent_checkpoint_id, "legacy_chk_41")
        self.assertEqual(universal.context, "Migrated auth middleware to bearer tokens")
        self.assertEqual(universal.provenance.provenance_type, ProvenanceType.AUTO_CAPTURED)
        self.assertEqual(universal.provenance.captured_by, "chatgpt")
        self.assertFalse(universal.provenance.is_authoritative)
        self.assertEqual(universal.permitted_excerpts, ["<context>Token verified</context>"])
        self.assertIsNotNone(universal.resume_brief)
        self.assertIn("Migrated auth middleware", universal.resume_brief.purpose)

    def test_serialization_round_trip(self):
        """Verify dictionary serialization and deserialization round-trip maintains exact state."""
        cp = UniversalCheckpoint.create_minimal(activity_id="act_roundtrip_test", context="Initial context")
        cp.completed_work.append("Drafted architecture")
        cp.pending_actions.append("Write tests")
        cp.decisions.append(
            DecisionRecord(id="dec_test", decision="Use JSON dataclasses", rationale="Zero external dependencies")
        )
        cp.artifacts.append(
            ArtifactReference(name="spec.md", path_or_uri="docs/spec.md", mode=ArtifactMode.REFERENCE)
        )
        cp.resume_brief = ResumeBrief(
            purpose="Testing serialization round-trip",
            last_completed_work=["Drafted architecture"],
            next_actions=["Write tests"]
        )

        data = cp.to_dict()
        restored = UniversalCheckpoint.from_dict(data)

        self.assertEqual(restored.id, cp.id)
        self.assertEqual(restored.activity_id, cp.activity_id)
        self.assertEqual(restored.context, cp.context)
        self.assertEqual(restored.completed_work, ["Drafted architecture"])
        self.assertEqual(restored.pending_actions, ["Write tests"])
        self.assertEqual(len(restored.decisions), 1)
        self.assertEqual(restored.decisions[0].decision, "Use JSON dataclasses")
        self.assertEqual(len(restored.artifacts), 1)
        self.assertEqual(restored.artifacts[0].name, "spec.md")
        self.assertIsNotNone(restored.resume_brief)
        self.assertEqual(restored.resume_brief.purpose, "Testing serialization round-trip")


if __name__ == "__main__":
    unittest.main()
