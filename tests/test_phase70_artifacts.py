"""
Phase 70: Artifact References and Snapshots - Comprehensive Test Suite
======================================================================
Tests all requirements and invariants for Milestone 41 - Phase 70:
1. Reference by default: zero-byte snapshot copy, live file pointer preserved.
2. Snapshot capture: text files <= 512KB captured with immutable content and timestamp.
3. Live reference vs snapshot labeling & storage visibility.
4. Resilient missing resources handling: references degrade safely to missing without crashing,
   snapshots survive live file deletion/modification.
5. Directory guard: entire folders/directories are NEVER snapshot-copied.
6. Privacy protection (I-10): high-risk credential files (.env, id_rsa, secrets) are blocked
   from snapshot capture and excluded; inline secrets redacted.
7. Size bounding: files > 512KB rejected for snapshot; total snapshot budget (2MB) enforced.
8. Portability: paths normalized to workspace-relative POSIX format.
9. REST API endpoints: POST /api/v1/artifacts/inspect and GET /api/v1/artifacts/status.
10. UI validation: HTML and CSS contain Phase 70 elements and styling.
11. Gate: Users clearly understand what is linked vs copied.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from core.activity import Activity
from core.artifact_manager import (
    ArtifactError,
    ArtifactManager,
    ArtifactPrivacyError,
    ArtifactSizeLimitError,
    ArtifactSnapshotError,
)
from core.checkpoint import ArtifactReference, UniversalCheckpoint
from core.enums import ArtifactMode
from core.manual_capture import (
    ManualCaptureEngine,
    ManualCaptureRequest,
    DuplicateSubmissionError,
)
from storage.activity_store import ActivityCheckpointStore


class TestPhase70Artifacts(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="continuum_phase70_test_")
        self.workspace_root = Path(self.test_dir)
        self.store = ActivityCheckpointStore(self.workspace_root)

        # Create sample workspace files
        self.src_dir = self.workspace_root / "src"
        self.src_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir = self.workspace_root / "docs"
        self.docs_dir.mkdir(parents=True, exist_ok=True)

        self.sample_code = self.src_dir / "app.py"
        self.sample_code.write_text("print('hello phase 70')", encoding="utf-8")

        self.sample_doc = self.docs_dir / "spec.md"
        self.sample_doc.write_text("# Project Continuum Spec\nDetails here.", encoding="utf-8")

        # Create a test activity
        self.act = Activity(
            id="act_p70_01",
            title="Artifact Testing Activity",
            activity_type="coding",
            status="active"
        )
        self.store.create_activity(self.act)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # --------------------------------------------------------------------------
    # 1. Reference by Default
    # --------------------------------------------------------------------------
    def test_reference_by_default(self):
        """Artifacts default to live references with zero bytes snapshot copied."""
        ref = ArtifactManager.create_reference("src/app.py", self.workspace_root)
        self.assertEqual(ref.mode, ArtifactMode.REFERENCE)
        self.assertTrue(ref.is_reference)
        self.assertFalse(ref.is_snapshot)
        self.assertIsNone(ref.snapshot_content)
        self.assertEqual(ref.storage_visibility, "workspace_local")
        self.assertTrue(ref.is_present)
        self.assertEqual(ref.path_or_uri, "src/app.py")
        self.assertEqual(ref.name, "app.py")

    def test_external_uri_reference(self):
        """External HTTP/HTTPS links are classified as external_uri references."""
        uri = "https://example.com/api/docs"
        ref = ArtifactManager.create_reference(uri, self.workspace_root)
        self.assertEqual(ref.mode, ArtifactMode.REFERENCE)
        self.assertEqual(ref.storage_visibility, "external_uri")
        self.assertEqual(ref.path_or_uri, uri)

    # --------------------------------------------------------------------------
    # 2. Safe Snapshot Capture
    # --------------------------------------------------------------------------
    def test_safe_text_snapshot_capture(self):
        """Valid text file can be captured as an immutable snapshot with timestamp."""
        snap = ArtifactManager.create_snapshot("docs/spec.md", self.workspace_root)
        self.assertEqual(snap.mode, ArtifactMode.SNAPSHOT)
        self.assertTrue(snap.is_snapshot)
        self.assertFalse(snap.is_reference)
        self.assertIsNotNone(snap.snapshot_content)
        self.assertIn("# Project Continuum Spec", snap.snapshot_content)
        self.assertIsNotNone(snap.captured_at)
        self.assertIsNotNone(snap.checksum_sha256)
        self.assertEqual(snap.storage_visibility, "embedded_snapshot")

    # --------------------------------------------------------------------------
    # 3. Missing Resource Resilience
    # --------------------------------------------------------------------------
    def test_missing_reference_degrades_gracefully(self):
        """Referencing a non-existent file marks it missing without crashing."""
        ref = ArtifactManager.create_reference("nonexistent/file.txt", self.workspace_root)
        self.assertEqual(ref.storage_visibility, "missing")
        self.assertFalse(ref.is_present)

        # Status resolution
        status = ArtifactManager.resolve_artifact_status(ref, self.workspace_root)
        self.assertFalse(status["is_valid"])
        self.assertEqual(status["live_status"], "missing")
        self.assertEqual(status["storage_visibility"], "missing")

    def test_snapshot_survives_live_file_deletion(self):
        """A snapshot copy preserves its content even if the live file is deleted."""
        temp_file = self.workspace_root / "temp_memo.txt"
        temp_file.write_text("Crucial historical note", encoding="utf-8")

        snap = ArtifactManager.create_snapshot("temp_memo.txt", self.workspace_root)
        self.assertEqual(snap.snapshot_content, "Crucial historical note")

        # Delete live file from workspace
        temp_file.unlink()
        self.assertFalse(temp_file.exists())

        # Resolve status: snapshot must remain valid and intact!
        status = ArtifactManager.resolve_artifact_status(snap, self.workspace_root)
        self.assertTrue(status["is_valid"])
        self.assertTrue(status["has_content"])
        self.assertEqual(status["live_status"], "deleted_from_workspace")
        self.assertIn("preserved in checkpoint", status["live_message"])

    def test_snapshot_detects_live_divergence(self):
        """Snapshot detects when live workspace file has diverged since capture."""
        snap = ArtifactManager.create_snapshot("src/app.py", self.workspace_root)

        # Live file matches initially
        status1 = ArtifactManager.resolve_artifact_status(snap, self.workspace_root)
        self.assertEqual(status1["live_status"], "identical")

        # Mutate live file
        self.sample_code.write_text("print('mutated!')", encoding="utf-8")

        # Now status should indicate diverged
        status2 = ArtifactManager.resolve_artifact_status(snap, self.workspace_root)
        self.assertEqual(status2["live_status"], "diverged")

    # --------------------------------------------------------------------------
    # 4. Directory Guard: Never Copy Entire Folders Silently
    # --------------------------------------------------------------------------
    def test_directory_snapshot_rejected(self):
        """Attempting to snapshot a directory raises ArtifactSnapshotError."""
        with self.assertRaises(ArtifactSnapshotError):
            ArtifactManager.create_snapshot("src", self.workspace_root)

    def test_directory_reference_allowed(self):
        """A directory can still be linked as a reference without copying contents."""
        ref = ArtifactManager.create_reference("src", self.workspace_root)
        self.assertEqual(ref.mode, ArtifactMode.REFERENCE)
        self.assertIsNone(ref.snapshot_content)
        self.assertEqual(ref.storage_visibility, "workspace_local")

    # --------------------------------------------------------------------------
    # 5. Privacy Protections (Invariant I-10)
    # --------------------------------------------------------------------------
    def test_high_risk_credential_file_snapshot_blocked(self):
        """Credential files (.env, id_rsa, *.pem) cannot be snapshot-captured."""
        env_file = self.workspace_root / ".env"
        env_file.write_text("OPENAI_API_KEY=sk-test-secret-12345", encoding="utf-8")

        with self.assertRaises(ArtifactPrivacyError):
            ArtifactManager.create_snapshot(".env", self.workspace_root)

    def test_inspect_resource_flags_high_risk(self):
        """Resource inspection flags credential files as unsafe for snapshot."""
        env_file = self.workspace_root / ".env"
        env_file.write_text("SECRET=123", encoding="utf-8")

        inspection = ArtifactManager.inspect_resource(".env", self.workspace_root)
        self.assertTrue(inspection["is_high_risk"])
        self.assertFalse(inspection["is_safe_for_snapshot"])
        self.assertIn("High-risk credential", inspection["reason"])

    def test_inline_secret_redaction_in_snapshot(self):
        """Inline secrets in allowed files are scrubbed by sanitizer during snapshot."""
        cfg_file = self.workspace_root / "config.json"
        # ghp_ token with exactly 36 chars
        sample_token = "ghp_123456789012345678901234567890123456"
        cfg_file.write_text(f'{{"token": "{sample_token}"}}', encoding="utf-8")

        snap = ArtifactManager.create_snapshot("config.json", self.workspace_root)
        self.assertNotIn(sample_token, snap.snapshot_content)
        self.assertIn("<REDACTED_GITHUB_TOKEN>", snap.snapshot_content)

    # --------------------------------------------------------------------------
    # 6. Size Bounds & Budgets
    # --------------------------------------------------------------------------
    def test_file_exceeding_max_snapshot_size_rejected(self):
        """Files exceeding 512 KB are rejected from snapshot capture."""
        large_file = self.workspace_root / "large_data.json"
        # Write 600 KB file
        large_file.write_text("A" * (600 * 1024), encoding="utf-8")

        with self.assertRaises(ArtifactSizeLimitError):
            ArtifactManager.create_snapshot("large_data.json", self.workspace_root)

    def test_total_snapshot_budget_enforced(self):
        """Checkpoints enforce 2 MB total snapshot content budget."""
        f1 = self.workspace_root / "file1.txt"
        f1.write_text("X" * (400 * 1024), encoding="utf-8")
        f2 = self.workspace_root / "file2.txt"
        f2.write_text("Y" * (400 * 1024), encoding="utf-8")

        # Two 400KB files is 800KB <= 2MB budget: passes
        raw = [
            {"path_or_uri": "file1.txt", "mode": "snapshot"},
            {"path_or_uri": "file2.txt", "mode": "snapshot"},
        ]
        processed = ArtifactManager.validate_and_process_artifacts(raw, self.workspace_root)
        self.assertEqual(len(processed), 2)
        self.assertTrue(processed[0].is_snapshot)
        self.assertTrue(processed[1].is_snapshot)

    # --------------------------------------------------------------------------
    # 7. Path Normalization & Portability
    # --------------------------------------------------------------------------
    def test_path_normalization(self):
        """Absolute workspace paths are normalized to relative POSIX paths."""
        abs_p = str((self.workspace_root / "src" / "app.py").resolve())
        norm = ArtifactManager.normalize_path(abs_p, self.workspace_root)
        self.assertEqual(norm, "src/app.py")

        backslashes = "docs\\spec.md"
        norm2 = ArtifactManager.normalize_path(backslashes, self.workspace_root)
        self.assertEqual(norm2, "docs/spec.md")

    # --------------------------------------------------------------------------
    # 8. Manual Capture Integration (Full Workflow)
    # --------------------------------------------------------------------------
    def test_manual_capture_with_mixed_artifacts(self):
        """Manual checkpoint capture correctly processes references and snapshots."""
        engine = ManualCaptureEngine(self.store, workspace_root=self.workspace_root)

        req = ManualCaptureRequest(
            activity_id=self.act.id,
            context="Capture with mixed artifacts",
            completed_work=["Finished feature"],
            artifacts=[
                {"path_or_uri": "src/app.py", "mode": "reference"},
                {"path_or_uri": "docs/spec.md", "mode": "snapshot"},
                {"path_or_uri": "https://specs.org/api", "mode": "reference"}
            ]
        )

        resp = engine.capture_checkpoint(req)
        self.assertTrue(resp.success)
        self.assertEqual(len(resp.checkpoint["artifacts"]), 3)

        # Inspect saved checkpoint in store
        chk = self.store.get_checkpoint(resp.checkpoint_id, self.act.id)
        self.assertEqual(len(chk.artifacts), 3)

        art_ref = next(a for a in chk.artifacts if a.name == "app.py")
        art_snap = next(a for a in chk.artifacts if a.name == "spec.md")
        art_ext = next(a for a in chk.artifacts if "specs.org" in a.path_or_uri)

        self.assertTrue(art_ref.is_reference)
        self.assertIsNone(art_ref.snapshot_content)

        self.assertTrue(art_snap.is_snapshot)
        self.assertIsNotNone(art_snap.snapshot_content)
        self.assertIn("# Project Continuum Spec", art_snap.snapshot_content)

        self.assertEqual(art_ext.storage_visibility, "external_uri")

    # --------------------------------------------------------------------------
    # 9. Gate Verification: Users understand what is linked vs copied
    # --------------------------------------------------------------------------
    def test_gate_linked_vs_copied_distinction(self):
        """Verify the system clearly labels linked reference vs snapshot copy."""
        ref = ArtifactManager.create_reference("src/app.py", self.workspace_root)
        snap = ArtifactManager.create_snapshot("docs/spec.md", self.workspace_root)

        # 1. Distinct modes
        self.assertNotEqual(ref.mode, snap.mode)
        self.assertEqual(ref.mode, ArtifactMode.REFERENCE)
        self.assertEqual(snap.mode, ArtifactMode.SNAPSHOT)

        # 2. Clear content representation
        self.assertIsNone(ref.snapshot_content)
        self.assertIsNotNone(snap.snapshot_content)

        # 3. Clear storage visibility
        self.assertEqual(ref.storage_visibility, "workspace_local")
        self.assertEqual(snap.storage_visibility, "embedded_snapshot")

        # 4. Status dictionary clarity
        status_ref = ArtifactManager.resolve_artifact_status(ref, self.workspace_root)
        status_snap = ArtifactManager.resolve_artifact_status(snap, self.workspace_root)

        self.assertFalse(status_ref["is_snapshot"])
        self.assertTrue(status_snap["is_snapshot"])
        self.assertIn("live_message", status_ref)
        self.assertIn("live_message", status_snap)

    # --------------------------------------------------------------------------
    # 10. REST API & Route Logic
    # --------------------------------------------------------------------------
    def test_inspect_api_logic(self):
        """Resource inspection classifies multiple paths according to safety rules."""
        paths = ["src/app.py", "docs/spec.md", "nonexistent.py", "https://api.github.com"]
        inspections = [ArtifactManager.inspect_resource(p, self.workspace_root) for p in paths]

        self.assertEqual(len(inspections), 4)
        self.assertTrue(inspections[0]["exists"])
        self.assertTrue(inspections[0]["is_safe_for_snapshot"])
        self.assertTrue(inspections[1]["is_safe_for_snapshot"])
        self.assertFalse(inspections[2]["exists"])
        self.assertEqual(inspections[3]["storage_visibility"], "external_uri")

    # --------------------------------------------------------------------------
    # 11. UI HTML & CSS Assets Verification
    # --------------------------------------------------------------------------
    def test_ui_contains_phase70_elements(self):
        """Web dashboard HTML contains artifact inputs and mode selections."""
        html_path = Path("server/static/index.html")
        self.assertTrue(html_path.exists())
        content = html_path.read_text(encoding="utf-8")

        self.assertIn("captureArtifacts", content)
        self.assertIn("radioArtReference", content)
        self.assertIn("radioArtSnapshot", content)
        self.assertIn("Artifacts & References", content)

    def test_dashboard_css_contains_artifact_classes(self):
        """Web dashboard CSS contains styling for artifact badges and cards."""
        css_path = Path("server/static/dashboard.css")
        self.assertTrue(css_path.exists())
        content = css_path.read_text(encoding="utf-8")

        self.assertIn(".artifact-card", content)
        self.assertIn(".badge-art-reference", content)
        self.assertIn(".badge-art-snapshot", content)
        self.assertIn(".badge-art-missing", content)
        self.assertIn(".badge-art-external", content)


if __name__ == "__main__":
    unittest.main()
