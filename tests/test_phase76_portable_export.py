"""
Unit and Contract Tests for Phase 76 - Portable Versioned Export.
Milestone 43: Backup, Restore and Portability.

Covers:
1. Single activity export.
2. Multiple activity export.
3. Selective checkpoints under activities.
4. Empty and large selection handling.
5. Preservation of IDs, relations, DAG lineage, provenance, and artifact distinctions (live vs snapshot).
6. Secrets and privacy exclusions applied.
7. Version metadata validation (continuum-export-v1.0).
8. Gate Invariant: Portable export is explicitly labeled and NOT misrepresented as a complete backup.
"""

import json
import os
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path

from core.activity import Activity
from core.checkpoint import (
    UniversalCheckpoint,
    DecisionRecord,
    ProvenanceRecord,
    ArtifactReference,
    ResumeBrief,
)
from core.enums import ArtifactMode, ProvenanceType
from core.privacy import PrivacyManager
from core.backup import (
    PORTABLE_EXPORT_FORMAT_VERSION,
    PortableExportEngine,
    PortableExportManifest,
    CorruptedBackupError,
)


class TestPhase76PortableExport(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="continuum_test_phase76_")
        self.workspace_root = Path(self.test_dir)
        self.continuum_dir = self.workspace_root / ".continuum"
        self.activities_dir = self.continuum_dir / "activities"
        self.activities_dir.mkdir(parents=True, exist_ok=True)

        self.privacy_mgr = PrivacyManager.get_instance(self.workspace_root)
        self.engine = PortableExportEngine(self.workspace_root, privacy_mgr=self.privacy_mgr)

        # Setup sample activities and checkpoints
        self._setup_sample_data()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _setup_sample_data(self):
        # Activity 1
        act1_dir = self.activities_dir / "act_001"
        act1_dir.mkdir(parents=True, exist_ok=True)
        act1 = Activity(
            id="act_001",
            title="Design Payment Pipeline",
            description="Integration of Stripe API for subscriptions",
            tags=["payment", "billing"],
        )
        with open(act1_dir / "activity.json", "w", encoding="utf-8") as f:
            json.dump(act1.to_dict(), f, indent=2)

        chk1_dir = act1_dir / "checkpoints"
        chk1_dir.mkdir(parents=True, exist_ok=True)

        # Root Checkpoint
        chk1 = UniversalCheckpoint(
            id="chk_001_root",
            activity_id="act_001",
            parent_checkpoint_id=None,
            completed_work=["Setup payment webhook handler"],
            pending_actions=["Configure webhook secret"],
            context="Initial architecture for billing webhook",
            decisions=[
                DecisionRecord(id="dec_01", decision="Use Stripe webhooks", rationale="Reliable events")
            ],
            artifacts=[
                ArtifactReference(
                    name="stripe_config.py",
                    path_or_uri="/path/stripe_config.py",
                    mode=ArtifactMode.REFERENCE,
                ),
                ArtifactReference(
                    name="snippet.txt",
                    path_or_uri="/path/snippet.txt",
                    mode=ArtifactMode.SNAPSHOT,
                    snapshot_content="WEBHOOK_VERSION=2023-10-16",
                ),
            ],
            provenance=ProvenanceRecord(
                provenance_type=ProvenanceType.USER_CONFIRMED,
                captured_by="alice",
            ),
        )
        with open(chk1_dir / "chk_001_root.json", "w", encoding="utf-8") as f:
            json.dump(chk1.to_dict(), f, indent=2)

        # Child Checkpoint (DAG lineage)
        chk2 = UniversalCheckpoint(
            id="chk_002_child",
            activity_id="act_001",
            parent_checkpoint_id="chk_001_root",
            completed_work=["Validated webhook signatures"],
            pending_actions=["Add telemetry metrics"],
            context="Signature validation completed",
            resume_brief=ResumeBrief(
                purpose="Implement billing subsystem",
                last_completed_work=["Validated webhook signatures"],
            ),
        )
        with open(chk1_dir / "chk_002_child.json", "w", encoding="utf-8") as f:
            json.dump(chk2.to_dict(), f, indent=2)

        # Activity 2
        act2_dir = self.activities_dir / "act_002"
        act2_dir.mkdir(parents=True, exist_ok=True)
        act2 = Activity(
            id="act_002",
            title="Setup Authentication",
            description="OAuth2 and session management",
            tags=["auth", "security"],
        )
        with open(act2_dir / "activity.json", "w", encoding="utf-8") as f:
            json.dump(act2.to_dict(), f, indent=2)

        chk2_dir = act2_dir / "checkpoints"
        chk2_dir.mkdir(parents=True, exist_ok=True)

        chk3 = UniversalCheckpoint(
            id="chk_003_auth",
            activity_id="act_002",
            parent_checkpoint_id=None,
            completed_work=["Implement JWT token generation"],
            context="JWT authentication flow",
        )
        with open(chk2_dir / "chk_003_auth.json", "w", encoding="utf-8") as f:
            json.dump(chk3.to_dict(), f, indent=2)

    def test_single_activity_export(self):
        """Verifies exporting a single activity includes only its checkpoints."""
        result = self.engine.export_selection(activity_ids=["act_001"])
        self.assertTrue(os.path.exists(result.archive_path))
        self.assertEqual(result.manifest.activity_count, 1)
        self.assertEqual(result.manifest.selected_activity_ids, ["act_001"])
        self.assertEqual(result.manifest.checkpoint_count, 2)
        self.assertIn("chk_001_root", result.manifest.selected_checkpoint_ids)
        self.assertIn("chk_002_child", result.manifest.selected_checkpoint_ids)
        self.assertNotIn("act_002", result.manifest.selected_activity_ids)

        # Verify export integrity
        verify = self.engine.verify_export(result.archive_path)
        self.assertTrue(verify["is_valid"])
        self.assertEqual(verify["activity_count"], 1)

    def test_multiple_activity_export(self):
        """Verifies exporting multiple activities bundles all requested activities."""
        result = self.engine.export_selection(activity_ids=["act_001", "act_002"])
        self.assertEqual(result.manifest.activity_count, 2)
        self.assertEqual(result.manifest.checkpoint_count, 3)
        self.assertEqual(len(result.manifest.file_manifest), 5)  # 2 activities + 3 checkpoints

        verify = self.engine.verify_export(result.archive_path)
        self.assertTrue(verify["is_valid"])

    def test_selective_checkpoints_export(self):
        """Verifies selective checkpoint filtering under activities."""
        # Request both activities but only chk_002_child and chk_003_auth
        result = self.engine.export_selection(
            activity_ids=["act_001", "act_002"],
            checkpoint_ids=["chk_002_child", "chk_003_auth"],
        )
        self.assertEqual(result.manifest.activity_count, 2)
        self.assertEqual(result.manifest.checkpoint_count, 2)
        self.assertNotIn("chk_001_root", result.manifest.selected_checkpoint_ids)
        self.assertIn("chk_002_child", result.manifest.selected_checkpoint_ids)
        self.assertIn("chk_003_auth", result.manifest.selected_checkpoint_ids)

    def test_empty_selection_handling(self):
        """Verifies explicit empty selection generates a valid archive with zero records."""
        result = self.engine.export_selection(activity_ids=[])
        self.assertEqual(result.manifest.activity_count, 0)
        self.assertEqual(result.manifest.checkpoint_count, 0)
        self.assertEqual(len(result.manifest.file_manifest), 0)

        verify = self.engine.verify_export(result.archive_path)
        self.assertTrue(verify["is_valid"])
        self.assertEqual(verify["activity_count"], 0)

    def test_large_selection_handling(self):
        """Verifies streaming and hash verification for a large selection of checkpoints."""
        large_act_dir = self.activities_dir / "act_large"
        large_act_dir.mkdir(parents=True, exist_ok=True)
        large_act = Activity(id="act_large", title="Large Dataset Test")
        with open(large_act_dir / "activity.json", "w", encoding="utf-8") as f:
            json.dump(large_act.to_dict(), f)

        chk_dir = large_act_dir / "checkpoints"
        chk_dir.mkdir(parents=True, exist_ok=True)

        for i in range(50):
            c = UniversalCheckpoint(
                id=f"chk_large_{i:03d}",
                activity_id="act_large",
                context=f"Checkpoint number {i} with payload data",
            )
            with open(chk_dir / f"chk_large_{i:03d}.json", "w", encoding="utf-8") as f:
                json.dump(c.to_dict(), f)

        result = self.engine.export_selection(activity_ids=["act_large"])
        self.assertEqual(result.manifest.activity_count, 1)
        self.assertEqual(result.manifest.checkpoint_count, 50)
        self.assertEqual(len(result.manifest.file_manifest), 51)

        verify = self.engine.verify_export(result.archive_path)
        self.assertTrue(verify["is_valid"])

    def test_ids_relations_dag_artifacts_preserved(self):
        """Verifies DAG parent relations, decisions, provenance and live vs snapshot artifact modes are preserved."""
        result = self.engine.export_selection(activity_ids=["act_001"])

        with tarfile.open(result.archive_path, "r:gz") as tar:
            # Check chk_001_root content
            f1 = tar.extractfile("activities/act_001/checkpoints/chk_001_root.json")
            self.assertIsNotNone(f1)
            c1_data = json.loads(f1.read().decode("utf-8"))
            self.assertIsNone(c1_data["parent_checkpoint_id"])
            self.assertEqual(len(c1_data["decisions"]), 1)
            self.assertEqual(c1_data["decisions"][0]["id"], "dec_01")
            self.assertEqual(c1_data["provenance"]["captured_by"], "alice")

            # Check artifacts
            artifacts = c1_data["artifacts"]
            self.assertEqual(len(artifacts), 2)
            art_ref = next(a for a in artifacts if a["name"] == "stripe_config.py")
            art_snap = next(a for a in artifacts if a["name"] == "snippet.txt")
            self.assertEqual(art_ref["mode"], "reference")
            self.assertIsNone(art_ref.get("snapshot_content"))
            self.assertEqual(art_snap["mode"], "snapshot")
            self.assertEqual(art_snap["snapshot_content"], "WEBHOOK_VERSION=2023-10-16")

            # Check chk_002_child DAG relation
            f2 = tar.extractfile("activities/act_001/checkpoints/chk_002_child.json")
            self.assertIsNotNone(f2)
            c2_data = json.loads(f2.read().decode("utf-8"))
            self.assertEqual(c2_data["parent_checkpoint_id"], "chk_001_root")
            self.assertEqual(c2_data["resume_brief"]["purpose"], "Implement billing subsystem")

    def test_secrets_and_privacy_redaction(self):
        """Verifies sensitive secrets are redacted across activities and checkpoints."""
        secret_act_dir = self.activities_dir / "act_secret"
        secret_act_dir.mkdir(parents=True, exist_ok=True)
        secret_act = Activity(
            id="act_secret",
            title="Deploy with ghp_111122223333444455556666777788889999 token",
            description="Using AWS AKIAIOSFODNN7EXAMPLE key",
        )
        with open(secret_act_dir / "activity.json", "w", encoding="utf-8") as f:
            json.dump(secret_act.to_dict(), f)

        chk_dir = secret_act_dir / "checkpoints"
        chk_dir.mkdir(parents=True, exist_ok=True)
        secret_chk = UniversalCheckpoint(
            id="chk_secret_01",
            activity_id="act_secret",
            context="Deployed with password=SecretPassword123! in environment",
            completed_work=["Pushed with ghp_111122223333444455556666777788889999"],
            decisions=[DecisionRecord(id="d1", decision="Store AKIAIOSFODNN7EXAMPLE securely")],
            artifacts=[
                ArtifactReference(
                    name="env.txt",
                    path_or_uri="/tmp/env.txt",
                    mode=ArtifactMode.SNAPSHOT,
                    snapshot_content="API_KEY=ghp_111122223333444455556666777788889999",
                )
            ],
        )
        with open(chk_dir / "chk_secret_01.json", "w", encoding="utf-8") as f:
            json.dump(secret_chk.to_dict(), f)

        result = self.engine.export_selection(activity_ids=["act_secret"])
        with tarfile.open(result.archive_path, "r:gz") as tar:
            act_raw = tar.extractfile("activities/act_secret/activity.json").read().decode("utf-8")
            chk_raw = tar.extractfile("activities/act_secret/checkpoints/chk_secret_01.json").read().decode("utf-8")

            # Secrets should be redacted
            self.assertNotIn("ghp_111122223333444455556666777788889999", act_raw)
            self.assertNotIn("AKIAIOSFODNN7EXAMPLE", act_raw)
            self.assertNotIn("ghp_111122223333444455556666777788889999", chk_raw)
            self.assertNotIn("AKIAIOSFODNN7EXAMPLE", chk_raw)
            self.assertIn("<REDACTED_", act_raw)
            self.assertIn("<REDACTED_", chk_raw)

    def test_version_metadata(self):
        """Verifies portable export manifest adheres to format continuum-export-v1.0."""
        result = self.engine.export_selection(activity_ids=["act_001"])
        self.assertEqual(result.manifest.format_version, PORTABLE_EXPORT_FORMAT_VERSION)
        self.assertEqual(result.manifest.format_version, "continuum-export-v1.0")
        self.assertTrue(result.manifest.created_at)

    def test_gate_invariant_export_not_misrepresented_as_full_backup(self):
        """
        Gate Invariant:
        Portable export is explicitly labeled and NOT misrepresented as a complete backup.
        """
        result = self.engine.export_selection(activity_ids=["act_001"])
        manifest = result.manifest
        self.assertIn("PORTABLE_EXPORT", manifest.archive_type)
        self.assertIn("NOT a complete system backup", manifest.archive_type)

        verify = self.engine.verify_export(result.archive_path)
        self.assertFalse(verify["is_complete_backup"])
        self.assertIn("PORTABLE_EXPORT", verify["archive_type"])


if __name__ == "__main__":
    unittest.main()
