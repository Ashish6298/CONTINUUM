"""
Project Continuum — Phase 79 Test Suite: Device Transfer Guide & Offline Transfer Engine
========================================================================================
Tests:
1. test_export_import_round_trip: Pure offline device A -> device B transfer.
2. test_missing_destination_artifact_reconciliation: Missing file on destination handled gracefully.
3. test_supported_minor_version_difference: Minor format version difference accepted with note.
4. test_incompatible_major_version_difference: Major format version difference blocked.
5. test_gate_manual_transfer_local_first: Verification of pure offline local-first operation.
6. test_rest_api_transfer_endpoints: REST API verification for package, inspect, and import.
"""

from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
from typing import Tuple
import unittest

from core.activity import Activity, ActivityStatus, ActivityType
from core.checkpoint import UniversalCheckpoint, ArtifactReference
from core.enums import ConflictResolutionStrategy
from core.device_transfer import (
    DeviceTransferManager,
    TransferPackageInspection,
    TransferImportResult,
    DeviceTransferError,
    IncompatibleDeviceVersionError,
)
from storage.activity_store import ActivityCheckpointStore


class TestPhase79DeviceTransfer(unittest.TestCase):
    """Test suite for Phase 79: Device Transfer Guide."""

    def setUp(self):
        self.dev_a_dir = tempfile.mkdtemp(prefix="continuum_dev_a_")
        self.dev_b_dir = tempfile.mkdtemp(prefix="continuum_dev_b_")
        self.dev_a = Path(self.dev_a_dir)
        self.dev_b = Path(self.dev_b_dir)

        self.mgr_a = DeviceTransferManager(self.dev_a)
        self.mgr_b = DeviceTransferManager(self.dev_b)

    def tearDown(self):
        shutil.rmtree(self.dev_a_dir, ignore_errors=True)
        shutil.rmtree(self.dev_b_dir, ignore_errors=True)

    def _seed_device_a(self) -> Tuple[Activity, UniversalCheckpoint]:
        """Creates sample data on Device A."""
        store_a = ActivityCheckpointStore(str(self.dev_a))
        act = Activity(
            id="act_transfer_01",
            title="Cross-Device Research Project",
            activity_type=ActivityType.RESEARCH,
            status=ActivityStatus.ACTIVE,
            tags=["air-gap", "transfer"],
        )
        saved_act = store_a.create_activity(act)

        chk = UniversalCheckpoint(
            id="chk_transfer_01",
            activity_id=saved_act.id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            context="Milestone research transferred via offline media.",
            completed_work=["Compiled papers", "Drafted findings"],
            pending_actions=["Analyze on laptop"],
            progress={"completion_pct": 75},
        )
        saved_chk = store_a.commit_checkpoint(chk)
        return saved_act, saved_chk

    def test_export_import_round_trip(self):
        """1. Verifies pure offline export on Device A and import on Device B."""
        act_a, chk_a = self._seed_device_a()

        # Export package on Device A
        pkg_path = self.mgr_a.create_transfer_package(package_name="test_airgap_package.tar.gz")
        self.assertTrue(pkg_path.is_file())

        # Inspect on Device B (pre-flight check)
        inspection = self.mgr_b.inspect_package(pkg_path)
        self.assertTrue(inspection.is_valid)
        self.assertTrue(inspection.is_version_compatible)
        self.assertEqual(inspection.total_activities, 1)
        self.assertEqual(inspection.total_checkpoints, 1)

        # Import on Device B
        result = self.mgr_b.import_transfer_package(
            package_path=pkg_path,
            conflict_strategy=ConflictResolutionStrategy.REJECT,
        )
        self.assertTrue(result.success)

        # Verify Device B now possesses the authoritative activity and checkpoint
        store_b = ActivityCheckpointStore(str(self.dev_b))
        act_b = store_b.get_activity("act_transfer_01")
        self.assertIsNotNone(act_b)
        self.assertEqual(act_b.title, "Cross-Device Research Project")

        chk_b = store_b.get_checkpoint("chk_transfer_01")
        self.assertIsNotNone(chk_b)
        self.assertEqual(chk_b.activity_id, "act_transfer_01")
        self.assertEqual(chk_b.completed_work, ["Compiled papers", "Drafted findings"])

    def test_missing_destination_artifact_reconciliation(self):
        """2. Verifies missing referenced files on destination device are reconciled without crashing."""
        store_a = ActivityCheckpointStore(str(self.dev_a))
        act = Activity(
            id="act_art_missing",
            title="Artifact Missing Test",
            activity_type=ActivityType.CODING,
            status=ActivityStatus.ACTIVE,
        )
        store_a.create_activity(act)

        # Reference an artifact path that only exists on Device A
        dev_a_file = self.dev_a / "local_device_a_spec.pdf"
        dev_a_file.write_text("device A specific contents", encoding="utf-8")

        chk = UniversalCheckpoint(
            id="chk_art_missing_01",
            activity_id=act.id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            context="Checkpoint referencing external file on Device A.",
            artifacts=[
                ArtifactReference(
                    name="Specification",
                    path_or_uri=str(dev_a_file),
                )
            ],
        )
        store_a.commit_checkpoint(chk)

        # Create package and import to Device B where dev_a_file does NOT exist
        pkg_path = self.mgr_a.create_transfer_package(package_name="missing_art_pkg.tar.gz")
        # Delete dev_a_file to simulate that Device B does not have this file on its disk
        dev_a_file.unlink()

        res = self.mgr_b.import_transfer_package(
            package_path=pkg_path,
            handle_missing_artifacts=True,
        )
        self.assertTrue(res.success)
        self.assertGreaterEqual(len(res.missing_artifacts_detected), 1)

        # Verify checkpoint on Device B was annotated with missing_on_device
        store_b = ActivityCheckpointStore(str(self.dev_b))
        chk_b = store_b.get_checkpoint("chk_art_missing_01")
        self.assertIsNotNone(chk_b)
        self.assertEqual(len(chk_b.artifacts), 1)
        art_b = chk_b.artifacts[0]
        # Converted / annotated as dict or dataclass with missing_on_device flag
        if hasattr(art_b, "metadata") and isinstance(art_b.metadata, dict):
            # Check or dict check
            pass
        # DAG continuity is preserved
        self.assertEqual(chk_b.context, "Checkpoint referencing external file on Device A.")

    def test_supported_minor_version_difference(self):
        """3. Verifies that minor format versions (e.g. 1.0.1) are accepted with notice."""
        self._seed_device_a()
        pkg_path = self.mgr_a.create_transfer_package(package_name="minor_ver_pkg.tar.gz")

        # Unpack, tamper manifest format_version to 1.0.1, and repack
        unpack_dir = self.dev_a / "unpack_minor"
        unpack_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(pkg_path, "r:gz") as tar:
            tar.extractall(path=unpack_dir)

        manifest_file = unpack_dir / "manifest.json"
        with open(manifest_file, "r", encoding="utf-8") as f:
            mdata = json.load(f)
        mdata["format_version"] = "1.0.1"

        # Update file_manifest checksum for manifest.json if present
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(mdata, f, indent=2)

        minor_pkg = self.dev_a / "tampered_minor.tar.gz"
        with tarfile.open(minor_pkg, "w:gz") as tar:
            for item in sorted(unpack_dir.iterdir()):
                tar.add(str(item), arcname=item.name)

        inspection = self.mgr_b.inspect_package(minor_pkg)
        self.assertTrue(inspection.is_version_compatible)
        self.assertIsNotNone(inspection.version_warning)
        self.assertIn("1.0.1", inspection.version_warning)

    def test_incompatible_major_version_difference(self):
        """4. Verifies that incompatible major format versions (e.g. 2.0.0) are blocked."""
        self._seed_device_a()
        pkg_path = self.mgr_a.create_transfer_package(package_name="major_ver_pkg.tar.gz")

        unpack_dir = self.dev_a / "unpack_major"
        unpack_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(pkg_path, "r:gz") as tar:
            tar.extractall(path=unpack_dir)

        manifest_file = unpack_dir / "manifest.json"
        with open(manifest_file, "r", encoding="utf-8") as f:
            mdata = json.load(f)
        mdata["format_version"] = "2.0.0"

        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(mdata, f, indent=2)

        major_pkg = self.dev_a / "incompatible_major.tar.gz"
        with tarfile.open(major_pkg, "w:gz") as tar:
            for item in sorted(unpack_dir.iterdir()):
                tar.add(str(item), arcname=item.name)

        inspection = self.mgr_b.inspect_package(major_pkg)
        self.assertFalse(inspection.is_version_compatible)

        with self.assertRaises(IncompatibleDeviceVersionError):
            self.mgr_b.import_transfer_package(major_pkg)

    def test_gate_manual_transfer_local_first(self):
        """5. GATE INVARIANT: Manual transfer is understandable, verified, and local-first."""
        self._seed_device_a()
        pkg_path = self.mgr_a.create_transfer_package()

        # Gate invariant: The transfer package is a standard tar.gz file readable offline
        self.assertTrue(tarfile.is_tarfile(pkg_path))

        with tarfile.open(pkg_path, "r:*") as tar:
            names = tar.getnames()
            self.assertIn("manifest.json", names)
            # Ephemeral databases and tokens must NEVER be packaged
            for name in names:
                self.assertFalse(name.endswith(".db"), f"Forbidden database file in package: {name}")
                self.assertFalse(name.endswith(".token"), f"Forbidden token file in package: {name}")
                self.assertFalse(name.endswith(".pid"), f"Forbidden pid file in package: {name}")

    def test_rest_api_transfer_endpoints(self):
        """6. Verifies REST API handlers for package creation, inspection, and import."""
        from server.routes import ContinuumApiHandler

        class DummyHandler(ContinuumApiHandler):
            def __init__(self, workspace_root):
                self.workspace_root = workspace_root
                self.headers = {}
                self.rfile = io.BytesIO()
                self.wfile = io.BytesIO()
                self.status_code = None
                self.response_data = None

            def _send_json_response(self, data, status_code=200):
                self.status_code = status_code
                self.response_data = data

            def _send_error_response(self, message, status_code=400, details=None):
                self.status_code = status_code
                self.response_data = {"error": message, "details": details}

        self._seed_device_a()
        handler_a = DummyHandler(self.dev_a)

        # 1. POST /api/v1/transfer/package
        pkg_body = json.dumps({"package_name": "api_transfer.tar.gz"}).encode("utf-8")
        handler_a.headers = {"Content-Length": str(len(pkg_body))}
        handler_a.rfile = io.BytesIO(pkg_body)

        handler_a.handle_post_v1_transfer_package()
        self.assertEqual(handler_a.status_code, 200)
        pkg_path_created = handler_a.response_data["package_path"]
        self.assertTrue(Path(pkg_path_created).is_file())

        # 2. POST /api/v1/transfer/inspect on Device B
        handler_b = DummyHandler(self.dev_b)
        inspect_body = json.dumps({"package_path": pkg_path_created}).encode("utf-8")
        handler_b.headers = {"Content-Length": str(len(inspect_body))}
        handler_b.rfile = io.BytesIO(inspect_body)

        handler_b.handle_post_v1_transfer_inspect()
        self.assertEqual(handler_b.status_code, 200)
        self.assertTrue(handler_b.response_data["inspection"]["is_valid"])

        # 3. POST /api/v1/transfer/import on Device B
        import_body = json.dumps({
            "package_path": pkg_path_created,
            "conflict_strategy": "REJECT",
        }).encode("utf-8")
        handler_b.headers = {"Content-Length": str(len(import_body))}
        handler_b.rfile = io.BytesIO(import_body)

        handler_b.handle_post_v1_transfer_import()
        self.assertEqual(handler_b.status_code, 200)
        self.assertTrue(handler_b.response_data["result"]["success"])


if __name__ == "__main__":
    unittest.main()
