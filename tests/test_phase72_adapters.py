"""
Phase 72: Continuity Core Interfaces and Adapters - Comprehensive Test Suite
============================================================================
Tests all requirements and invariants for Milestone 41 - Phase 72:
1. Stable Core Interfaces verification:
   - Verification that `ActivityCheckpointStore`, `DeterministicResumeBriefGenerator`,
     `CheckpointDiffEngine`, and `StorageConsistencyAuditor` implement their protocols
     (runtime checkable protocols: ILifecycleManager, ICheckpointManager, etc.).
2. Repository Integration Adapters:
   - GitIntegrationAdapter: Least privilege, bounded queries, git commit checkpoint capture.
   - WorkspaceIntegrationAdapter: Safe file inspection, path traversal containment, file size limits.
   - RestApiIntegrationAdapter: Payload bounding, malformed JSON detection, secret redaction.
3. Payload Bounding & Least Privilege:
   - Oversized payloads (>2MB) are rejected with AdapterPayloadLimitError.
   - Oversized text excerpts (>64KB) are cleanly clamped.
4. Resilient Error Handling & Failure Isolation:
   - Malformed inputs raise clean AdapterMalformedInputError.
   - Path escaping or secret file access raises AdapterPermissionDeniedError.
   - Adapter failures CANNOT corrupt core storage.
5. Gate Invariant:
   - "Adapters cannot bypass core invariants."
   - Checkpoints produced by adapters strictly pass UniversalCheckpoint validation
     and DaemonSanitizer before reaching persistence.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from core.activity import Activity, ActivityStatus, ActivityType
from core.adapters import (
    AdapterMalformedInputError,
    AdapterPayloadLimitError,
    AdapterPermissionDeniedError,
    GitIntegrationAdapter,
    RestApiIntegrationAdapter,
    WorkspaceIntegrationAdapter,
)
from core.checkpoint import ArtifactReference, UniversalCheckpoint
from core.checkpoint_diff import CheckpointDiffEngine
from core.enums import ArtifactMode, ProvenanceType
from core.interfaces import (
    IBranchManager,
    ICheckpointManager,
    IHistoryManager,
    IIntegrityManager,
    ILifecycleManager,
    IRestoreManager,
    IResumeEngine,
)
from core.resume_generator import DeterministicResumeBriefGenerator
from storage.activity_store import ActivityCheckpointStore, ActivityNotFoundError
from storage.consistency import StorageConsistencyAuditor


class TestPhase72InterfacesAndAdapters(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="continuum_phase72_test_")
        self.workspace_root = Path(self.test_dir)
        self.store = ActivityCheckpointStore(self.workspace_root)

        # Create active test activity
        self.activity = self.store.create_activity(
            Activity(
                id="act_p72_test_01",
                title="Phase 72 Integration Test Activity",
                description="Testing core interfaces, adapters, and invariant guards",
                activity_type="coding",
                status=ActivityStatus.ACTIVE,
            )
        )

        # Create sample workspace files
        self.src_dir = self.workspace_root / "src"
        self.src_dir.mkdir(parents=True, exist_ok=True)
        self.sample_file = self.src_dir / "service.py"
        self.sample_file.write_text("class CoreService:\n    pass\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_core_interfaces_protocol_conformance(self):
        """Verifies that core domain managers adhere to the newly defined Protocol interfaces."""
        # 1. ActivityCheckpointStore implements ILifecycleManager, ICheckpointManager, IBranchManager, IRestoreManager
        self.assertTrue(isinstance(self.store, ILifecycleManager))
        self.assertTrue(isinstance(self.store, ICheckpointManager))
        self.assertTrue(isinstance(self.store, IBranchManager))
        self.assertTrue(isinstance(self.store, IRestoreManager))

        # 2. DeterministicResumeBriefGenerator implements IResumeEngine
        brief_gen = DeterministicResumeBriefGenerator()
        self.assertTrue(isinstance(brief_gen, IResumeEngine))

        # 3. StorageConsistencyAuditor implements IIntegrityManager
        auditor = StorageConsistencyAuditor(str(self.workspace_root))
        self.assertTrue(isinstance(auditor, IIntegrityManager))

    def test_git_adapter_non_git_workspace_graceful_handling(self):
        """Verifies GitIntegrationAdapter handles non-git directory safely without throwing uncaught exceptions."""
        adapter = GitIntegrationAdapter(self.workspace_root, store=self.store)
        self.assertFalse(adapter.is_git_repository())
        self.assertIsNone(adapter.get_current_branch())
        self.assertIsNone(adapter.get_head_commit())
        self.assertEqual(adapter.get_changed_files(), [])

    def test_git_adapter_capture_checkpoint(self):
        """Verifies GitIntegrationAdapter captures valid AUTO_CAPTURED checkpoint safely."""
        adapter = GitIntegrationAdapter(self.workspace_root, store=self.store)
        chk = adapter.capture_git_checkpoint(
            activity_id=self.activity.id,
            context_override="Manual snapshot via git adapter",
        )
        self.assertIsNotNone(chk.id)
        self.assertEqual(chk.activity_id, self.activity.id)
        self.assertEqual(chk.provenance.provenance_type, ProvenanceType.AUTO_CAPTURED)
        self.assertFalse(chk.provenance.is_authoritative)

        # Confirm persisted in store
        persisted = self.store.get_checkpoint(chk.id, self.activity.id)
        self.assertEqual(persisted.id, chk.id)

    def test_workspace_adapter_safe_path_containment(self):
        """Verifies WorkspaceIntegrationAdapter blocks paths escaping workspace root (I-10)."""
        adapter = WorkspaceIntegrationAdapter(self.workspace_root, store=self.store)

        # Valid relative path inside workspace
        valid_path = adapter.resolve_safe_path("src/service.py")
        self.assertEqual(valid_path, self.sample_file.resolve())

        # Path escaping outside workspace root
        with self.assertRaises(AdapterPermissionDeniedError):
            adapter.resolve_safe_path("../../outside.txt")

    def test_workspace_adapter_read_artifact_with_bounds_and_privacy(self):
        """Verifies safe artifact reading, secret denial, and size limits."""
        adapter = WorkspaceIntegrationAdapter(self.workspace_root, store=self.store)

        # Normal read
        content = adapter.read_artifact_content("src/service.py")
        self.assertIn("class CoreService:", content)

        # Denial of high risk secret file
        secret_file = self.workspace_root / ".env"
        secret_file.write_text("DATABASE_URL=postgres://user:pass@localhost/db", encoding="utf-8")
        with self.assertRaises(AdapterPermissionDeniedError):
            adapter.read_artifact_content(".env")

        # Exceeding size limit
        large_file = self.workspace_root / "large.txt"
        large_file.write_text("A" * 1024, encoding="utf-8")
        with self.assertRaises(AdapterPayloadLimitError):
            adapter.read_artifact_content("large.txt", max_bytes=500)

    def test_rest_api_adapter_payload_bounding(self):
        """Verifies RestApiIntegrationAdapter rejects payloads exceeding MAX_PAYLOAD_BYTES (2MB)."""
        adapter = RestApiIntegrationAdapter(self.workspace_root, store=self.store)
        oversized_str = "x" * (2 * 1024 * 1024 + 100)

        with self.assertRaises(AdapterPayloadLimitError):
            adapter.parse_and_validate_activity_payload(oversized_str)

        with self.assertRaises(AdapterPayloadLimitError):
            adapter.parse_and_validate_checkpoint_payload(oversized_str)

    def test_rest_api_adapter_activity_payload_parsing_and_sanitization(self):
        """Verifies activity parsing, validation, and secret sanitization from REST payload."""
        adapter = RestApiIntegrationAdapter(self.workspace_root, store=self.store)

        payload = {
            "title": "Build API sk-1234567890abcdef1234567890abcdef",
            "description": "Connecting to postgres://admin:secretpass@db.local:5432/main",
            "status": "active",
            "tags": ["backend", "api"],
        }

        activity = adapter.parse_and_validate_activity_payload(payload)
        self.assertNotIn("sk-1234567890abcdef1234567890abcdef", activity.title)
        self.assertIn("<REDACTED_OPENAI_KEY>", activity.title)
        self.assertNotIn("secretpass", activity.description)
        self.assertIn("<REDACTED_PASSWORD>", activity.description)
        self.assertEqual(activity.status, ActivityStatus.ACTIVE)

    def test_rest_api_adapter_checkpoint_payload_parsing_and_sanitization(self):
        """Verifies checkpoint parsing, artifact filtering, and secret sanitization from REST payload."""
        adapter = RestApiIntegrationAdapter(self.workspace_root, store=self.store)

        payload = {
            "activity_id": self.activity.id,
            "context": "Working on ghp_123456789012345678901234567890123456 feature",
            "completed_work": ["Implemented auth router"],
            "pending_actions": ["Write tests"],
            "artifacts": [
                {"name": "service.py", "path": "src/service.py", "mode": "reference"},
                {"name": ".env", "path": ".env", "mode": "reference"},  # High risk - must be dropped
            ],
            "decisions": [
                {"decision": "Use SQLite for derived indexing", "rationale": "Zero external dependencies"}
            ],
        }

        chk = adapter.parse_and_validate_checkpoint_payload(payload)
        self.assertNotIn("ghp_123456789012345678901234567890123456", chk.context)
        self.assertIn("<REDACTED_GITHUB_TOKEN>", chk.context)

        # Confirm .env was filtered out
        artifact_names = [a.name for a in chk.artifacts]
        self.assertIn("service.py", artifact_names)
        self.assertNotIn(".env", artifact_names)

        # Confirm decisions parsed
        self.assertEqual(len(chk.decisions), 1)
        self.assertEqual(chk.decisions[0].decision, "Use SQLite for derived indexing")

    def test_rest_api_adapter_malformed_input_rejection(self):
        """Verifies adapter cleanly raises AdapterMalformedInputError on corrupt/invalid inputs."""
        adapter = RestApiIntegrationAdapter(self.workspace_root, store=self.store)

        # Invalid JSON
        with self.assertRaises(AdapterMalformedInputError):
            adapter.parse_and_validate_activity_payload("{invalid_json: true")

        # Missing title in activity
        with self.assertRaises(AdapterMalformedInputError):
            adapter.parse_and_validate_activity_payload({"title": ""})

        # Missing activity_id in checkpoint
        with self.assertRaises(AdapterMalformedInputError):
            adapter.parse_and_validate_checkpoint_payload({"context": "hello"})

    def test_gate_adapters_cannot_bypass_core_invariants(self):
        """
        GATE INVARIANT TEST:
        Adapters cannot bypass core invariants (schema validation, immutability, privacy).
        1. Attempting to commit a checkpoint for a non-existent activity fails.
        2. Checkpoint validation cannot be bypassed by adapter payload.
        3. Core storage integrity remains completely intact after failed adapter operations.
        """
        adapter = RestApiIntegrationAdapter(self.workspace_root, store=self.store)

        # 1. Non-existent activity rejection
        payload_missing_act = {
            "activity_id": "act_does_not_exist_at_all",
            "context": "Test checkpoint for non-existent activity",
        }
        chk = adapter.parse_and_validate_checkpoint_payload(payload_missing_act)

        # Committing to store must fail with ActivityNotFoundError / DanglingReferenceError
        with self.assertRaises(Exception):
            self.store.commit_checkpoint(chk)

        # 2. Verify that our existing activity and checkpoints are clean and intact
        act = self.store.get_activity(self.activity.id)
        self.assertEqual(act.id, self.activity.id)
        auditor = StorageConsistencyAuditor(str(self.workspace_root))
        report = auditor.audit()
        self.assertTrue(report.is_clean)


if __name__ == "__main__":
    unittest.main()
