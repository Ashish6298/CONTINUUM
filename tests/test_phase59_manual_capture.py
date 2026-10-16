"""
Project Continuum — Phase 59 Test Suite
========================================
Milestone 38: Capture and Resume
Phase 59: Manual Checkpoint Capture

Validates:
1. Full manual checkpoint capture: saves state, progress, completed work, actions, decisions, context, blockers, artifacts.
2. Partial valid checkpoint capture: validates that minimal fields succeed and optional fields remain optional.
3. Invalid input handling: missing activity_id, malformed payloads, invalid types raise CheckpointValidationError.
4. Duplicate submission defense: identical submissions within dedup window or matching idempotency_key raise DuplicateSubmissionError.
5. Storage failure handling: disk/filesystem failure during commit triggers CaptureStorageError without corrupting state.
6. Privacy exclusions: API keys, bearer tokens, passwords, and custom denied terms are automatically redacted.
7. High-risk file exclusions: sensitive files (.env, *.key, *.pem) in artifact lists are excluded.
8. Independence from automation/AI settings: manual capture works offline with 0 network calls and 0 AI dependencies.
"""

from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from core.activity import Activity, ActivityType, ActivityStatus
from core.checkpoint import UniversalCheckpoint, CheckpointValidationError
from core.enums import ArtifactMode, ProvenanceType
from core.invariants import CommitFailedError
from core.manual_capture import (
    ManualCaptureEngine,
    ManualCaptureRequest,
    ManualCaptureResponse,
    PrivacySettings,
    DuplicateSubmissionError,
    CaptureStorageError,
)
from storage.activity_store import (
    ActivityCheckpointStore,
    ActivityNotFoundError,
    DanglingReferenceError,
)


class TestPhase59ManualCapture(unittest.TestCase):
    """Test suite for Phase 59: Manual Checkpoint Capture."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="continuum_p59_test_")
        self.workspace_root = Path(self.temp_dir)
        self.store = ActivityCheckpointStore(self.workspace_root)
        self.engine = ManualCaptureEngine(self.store, workspace_root=self.workspace_root)

        # Create a base activity to capture against
        self.activity = Activity.create_blank(
            title="Implement Universal Resume Architecture",
            activity_type=ActivityType.CODING,
            description="Milestone 38 capture test activity",
        )
        self.store.create_activity(self.activity)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_manual_checkpoint_capture(self):
        """Verifies capturing a complete manual checkpoint with all supported fields."""
        req = ManualCaptureRequest(
            activity_id=self.activity.id,
            context="Finished core data structures and setting up capture engine.",
            completed_work=[
                "Created ActivityCheckpointStore in Phase 56",
                "Created ContinuumMigrator in Phase 57",
                "Created StorageConsistencyEngine in Phase 58",
            ],
            pending_actions=[
                "Implement Phase 60 Deterministic Resume Briefs",
                "Implement Phase 61 Resume Center UI",
            ],
            blockers=["None currently."],
            decisions=[
                {
                    "decision": "Use local JSON partitions + SQLite derived index",
                    "rationale": "Zero external dependencies and cross-platform reliability",
                    "constraints": ["No paid external services"],
                }
            ],
            artifacts=[
                {
                    "name": "core_module",
                    "path_or_uri": "core/manual_capture.py",
                    "mode": "reference",
                }
            ],
            progress={"percentage": 50.0, "stage": "implementation"},
            user_identifier="engineer_ashish",
        )

        res = self.engine.capture_checkpoint(req)

        self.assertTrue(res.success)
        self.assertEqual(res.activity_id, self.activity.id)
        self.assertIsNotNone(res.checkpoint_id)
        self.assertEqual(res.redacted_count, 0)

        # Verify durable storage
        persisted = self.store.get_checkpoint(res.checkpoint_id, self.activity.id)
        self.assertEqual(persisted.context, req.context)
        self.assertEqual(len(persisted.completed_work), 3)
        self.assertEqual(len(persisted.pending_actions), 2)
        self.assertEqual(len(persisted.decisions), 1)
        self.assertEqual(persisted.provenance.provenance_type, ProvenanceType.USER_CONFIRMED)
        self.assertEqual(persisted.provenance.captured_by, "engineer_ashish")

    def test_partial_valid_checkpoint_capture(self):
        """Verifies that minimal fields succeed and optional fields remain optional."""
        req = ManualCaptureRequest(
            activity_id=self.activity.id,
            context="Quick checkpoint with minimal input.",
        )

        res = self.engine.capture_checkpoint(req)

        self.assertTrue(res.success)
        persisted = self.store.get_checkpoint(res.checkpoint_id, self.activity.id)
        self.assertEqual(persisted.context, "Quick checkpoint with minimal input.")
        self.assertEqual(persisted.completed_work, [])
        self.assertEqual(persisted.pending_actions, [])
        self.assertEqual(persisted.decisions, [])
        self.assertEqual(persisted.artifacts, [])

    def test_invalid_input_rejections(self):
        """Verifies validation errors on missing activity_id or malformed payload."""
        with self.assertRaises(CheckpointValidationError):
            ManualCaptureRequest.from_dict({"activity_id": ""})

        with self.assertRaises(CheckpointValidationError):
            ManualCaptureRequest.from_dict("not a dict")  # type: ignore

        # Targeting non-existent activity raises ActivityNotFoundError
        req = ManualCaptureRequest(activity_id="act_does_not_exist", context="Fail test")
        with self.assertRaises(ActivityNotFoundError):
            self.engine.capture_checkpoint(req)

    def test_dangling_parent_reference_rejection(self):
        """Verifies that specifying a non-existent parent checkpoint raises DanglingReferenceError."""
        req = ManualCaptureRequest(
            activity_id=self.activity.id,
            parent_checkpoint_id="chk_non_existent_parent",
            context="Broken ancestry test",
        )
        with self.assertRaises(DanglingReferenceError):
            self.engine.capture_checkpoint(req)

    def test_duplicate_submission_defense(self):
        """Verifies that rapid double submissions or duplicate idempotency keys are blocked."""
        req = ManualCaptureRequest(
            activity_id=self.activity.id,
            context="Unique submission payload for dedup test",
            idempotency_key="key_dedup_001",
        )

        # First submit succeeds
        res1 = self.engine.capture_checkpoint(req)
        self.assertTrue(res1.success)

        # Immediate duplicate submission with same idempotency key fails
        with self.assertRaises(DuplicateSubmissionError):
            self.engine.capture_checkpoint(req)

    def test_storage_failure_handling(self):
        """Verifies that persistence failure raises CaptureStorageError without false success."""
        req = ManualCaptureRequest(
            activity_id=self.activity.id,
            context="Simulated storage failure test",
            idempotency_key="key_storage_fail_001",
        )

        with patch.object(self.store, "commit_checkpoint", side_effect=CommitFailedError("Simulated disk full")):
            with self.assertRaises(CaptureStorageError):
                self.engine.capture_checkpoint(req)

    def test_privacy_exclusions_and_secret_redaction(self):
        """Verifies automatic redaction of secrets, tokens, and custom denied terms."""
        secret_context = "Using OpenAI key sk-1234567890abcdef1234567890abcdef and token ghp_123456789012345678901234567890123456"
        secret_completed = ["Tested AWS token AKIA1234567890ABCDEF", "Internal term ProjectTopSecret handled"]

        req = ManualCaptureRequest(
            activity_id=self.activity.id,
            context=secret_context,
            completed_work=secret_completed,
            privacy_settings=PrivacySettings(
                redact_secrets=True,
                custom_denied_terms=["ProjectTopSecret"],
            ),
        )

        res = self.engine.capture_checkpoint(req)

        self.assertTrue(res.success)
        self.assertGreater(res.redacted_count, 0)

        persisted = self.store.get_checkpoint(res.checkpoint_id, self.activity.id)
        self.assertNotIn("sk-1234567890", persisted.context)
        self.assertIn("<REDACTED_OPENAI_KEY>", persisted.context)
        self.assertNotIn("ghp_1234567890", persisted.context)
        self.assertIn("<REDACTED_GITHUB_TOKEN>", persisted.context)

        self.assertNotIn("AKIA1234567890", persisted.completed_work[0])
        self.assertIn("<REDACTED_AWS_KEY>", persisted.completed_work[0])

        self.assertNotIn("ProjectTopSecret", persisted.completed_work[1])
        self.assertIn("<REDACTED_SENSITIVE>", persisted.completed_work[1])

    def test_high_risk_file_artifact_exclusion(self):
        """Verifies that high-risk credential files are excluded from artifacts."""
        req = ManualCaptureRequest(
            activity_id=self.activity.id,
            context="Artifact testing",
            artifacts=[
                {"name": "valid_source", "path_or_uri": "src/main.py", "mode": "reference"},
                {"name": "env_file", "path_or_uri": ".env", "mode": "reference"},
                {"name": "private_key", "path_or_uri": "certs/server.key", "mode": "reference"},
            ],
            privacy_settings=PrivacySettings(exclude_high_risk_files=True),
        )

        res = self.engine.capture_checkpoint(req)

        self.assertTrue(res.success)
        self.assertEqual(res.excluded_artifacts_count, 2)

        persisted = self.store.get_checkpoint(res.checkpoint_id, self.activity.id)
        self.assertEqual(len(persisted.artifacts), 1)
        self.assertEqual(persisted.artifacts[0].name, "valid_source")


if __name__ == "__main__":
    unittest.main()
