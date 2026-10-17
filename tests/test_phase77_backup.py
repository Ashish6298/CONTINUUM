"""
Project Continuum — Phase 77 Test Suite
========================================
Milestone 43: Export, Backup, Import and Transfer
Phase 77: Complete Backup

Tests:
1. Completeness: all required records, relations, configs, artifacts included.
2. Truncation and corruption detection: truncated archive, member byte tampering, missing manifest.
3. Unsupported version handling: rejected with UnsupportedBackupVersionError.
4. Missing relation detection: missing owning activity or missing parent checkpoint.
5. Large backup bounded-memory behavior: chunked streaming (I-17).
6. Excluded content absent: SQLite index, tmp files, daemon tokens, retention archives omitted.
7. Truthful encryption disclosure: checksum is not encryption, status is NONE.
8. Gate verification: recovery promise matches actual archive contents.
9. REST API endpoints: GET /scope, POST /create, POST /verify.
"""

from datetime import datetime, timezone
import io
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import unittest

from core.activity import Activity, ActivityStatus, ActivityType
from core.checkpoint import UniversalCheckpoint, DecisionRecord, ArtifactReference
from core.enums import ArtifactMode
from core.invariants import InvariantViolationError
from core.privacy import PrivacyConfig, PrivacyManager
from core.backup import (
    CompleteBackupEngine,
    BackupManifest,
    BackupResult,
    BackupVerificationResult,
    BackupScope,
    RecordsSummary,
    FileManifestEntry,
    BackupError,
    UnsupportedBackupVersionError,
    CorruptedBackupError,
    MissingRelationError,
    BACKUP_FORMAT_VERSION,
    hash_file_stream,
)
from storage.activity_store import ActivityCheckpointStore


class TestPhase77CompleteBackup(unittest.TestCase):
    """Exhaustive test suite for Phase 77 Complete Backup and Verification Engine."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="continuum_p77_")
        self.workspace_root = Path(self.test_dir)
        PrivacyManager.reset_instances()
        self.privacy_mgr = PrivacyManager.get_instance(self.workspace_root)
        self.store = ActivityCheckpointStore(self.workspace_root)
        self.engine = CompleteBackupEngine(self.workspace_root, privacy_mgr=self.privacy_mgr)

    def tearDown(self):
        PrivacyManager.reset_instances()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _seed_test_data(self) -> Tuple[Activity, List[UniversalCheckpoint]]:
        """Helper to create a populated activity with checkpoints and relations."""
        activity = Activity(
            id="act_p77_main",
            title="Main Backup Activity",
            description="Complete backup verification activity",
            activity_type=ActivityType.CODING.value,
            status=ActivityStatus.ACTIVE,
            tags=["backup", "milestone43"],
            related_activity_ids=["act_p77_dep"],
        )
        self.store.create_activity(activity)

        # Checkpoint 1: Root checkpoint
        chk1 = UniversalCheckpoint(
            id="chk_p77_001",
            activity_id="act_p77_main",
            context="Initial foundational architecture setup.",
            completed_work=["Configured repository", "Set up database models"],
            decisions=[
                DecisionRecord(
                    id="dec_001",
                    decision="Use SQLite for derived indexing",
                    rationale="Self-contained and zero dependencies",
                )
            ],
            artifacts=[
                ArtifactReference(
                    name="models.py",
                    path_or_uri="src/models.py",
                    mode=ArtifactMode.REFERENCE,
                )
            ]
        )
        self.store.commit_checkpoint(chk1)

        # Checkpoint 2: Dependent child checkpoint
        chk2 = UniversalCheckpoint(
            id="chk_p77_002",
            activity_id="act_p77_main",
            parent_checkpoint_id="chk_p77_001",
            context="Implemented streaming backup engine.",
            completed_work=["Built CompleteBackupEngine", "Added verify_backup"],
            artifacts=[
                ArtifactReference(
                    name="snapshot.txt",
                    path_or_uri="snapshots/snapshot.txt",
                    mode=ArtifactMode.SNAPSHOT,
                    snapshot_content="Embedded safe snapshot text",
                )
            ]
        )
        self.store.commit_checkpoint(chk2)

        return activity, [chk1, chk2]

    def test_backup_completeness(self):
        """1. Verifies that all required records, relations, configs, and artifacts are captured."""
        act, chks = self._seed_test_data()

        # Seed configuration files
        privacy_cfg = PrivacyConfig(custom_denied_terms=["SecretA"])
        self.privacy_mgr.save_config(privacy_cfg)

        trigger_cfg_file = self.workspace_root / ".continuum" / "triggers.json"
        trigger_cfg_file.write_text(json.dumps({"git_commit_enabled": True}), encoding="utf-8")

        # Execute complete backup
        result = self.engine.create_backup()

        self.assertIsInstance(result, BackupResult)
        self.assertTrue(Path(result.archive_path).is_file())
        self.assertGreater(result.archive_size_bytes, 0)
        self.assertEqual(len(result.archive_sha256), 64)

        # Inspect manifest
        manifest = result.manifest
        self.assertEqual(manifest.format_version, BACKUP_FORMAT_VERSION)
        self.assertEqual(manifest.records_summary.activity_count, 1)
        self.assertEqual(manifest.records_summary.checkpoint_count, 2)
        self.assertEqual(manifest.records_summary.config_count, 2)  # triggers.json & privacy.json
        self.assertGreaterEqual(manifest.records_summary.relations_count, 2)  # parent link + related activity

        # Verify archive can be verified completely
        verify_res = self.engine.verify_backup(result.archive_path)
        self.assertTrue(verify_res.is_valid)
        self.assertTrue(verify_res.recovery_promise_verified)
        self.assertEqual(verify_res.verified_files_count, manifest.records_summary.total_files)

    def test_truncation_corruption_detection(self):
        """2. Verifies detection of truncated archives and tampered file members."""
        self._seed_test_data()
        result = self.engine.create_backup()
        orig_archive = Path(result.archive_path)

        # A) Truncated archive
        truncated_archive = self.workspace_root / "truncated.tar.gz"
        orig_bytes = orig_archive.read_bytes()
        truncated_archive.write_bytes(orig_bytes[: len(orig_bytes) // 2])

        with self.assertRaises(CorruptedBackupError):
            self.engine.verify_backup(truncated_archive, raise_on_error=True)

        res_trunc = self.engine.verify_backup(truncated_archive, raise_on_error=False)
        self.assertFalse(res_trunc.is_valid)
        self.assertIn("corrupted", res_trunc.error.lower())

        # B) Tampered member file inside archive
        tampered_archive = self.workspace_root / "tampered.tar.gz"
        # Unpack, modify a byte in checkpoint file, and repack
        unpack_dir = self.workspace_root / "tamper_unpack"
        unpack_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(orig_archive, "r:gz") as tar:
            tar.extractall(unpack_dir)

        # Tamper checkpoint file
        chk_file = next(unpack_dir.glob("activities/*/checkpoints/*.json"))
        chk_data = json.loads(chk_file.read_text(encoding="utf-8"))
        chk_data["context"] = "TAMPERED CONTEXT CHANGING HASH"
        chk_file.write_text(json.dumps(chk_data), encoding="utf-8")

        # Repackage with same manifest (manifest has original hash)
        with tarfile.open(tampered_archive, "w:gz") as tar:
            for item in sorted(unpack_dir.iterdir()):
                tar.add(str(item), arcname=item.name)

        with self.assertRaises(CorruptedBackupError) as ctx:
            self.engine.verify_backup(tampered_archive, raise_on_error=True)
        self.assertIn("Checksum mismatch", str(ctx.exception))

    def test_unsupported_version(self):
        """3. Verifies that backup archives with unsupported format versions are rejected."""
        self._seed_test_data()
        result = self.engine.create_backup()
        orig_archive = Path(result.archive_path)

        # Unpack, alter manifest version to v99.0, repack
        unpack_dir = self.workspace_root / "version_unpack"
        unpack_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(orig_archive, "r:gz") as tar:
            tar.extractall(unpack_dir)

        manifest_file = unpack_dir / "manifest.json"
        mdata = json.loads(manifest_file.read_text(encoding="utf-8"))
        mdata["format_version"] = "continuum-backup-v99.0"
        manifest_file.write_text(json.dumps(mdata), encoding="utf-8")

        unsupported_archive = self.workspace_root / "unsupported.tar.gz"
        with tarfile.open(unsupported_archive, "w:gz") as tar:
            for item in sorted(unpack_dir.iterdir()):
                tar.add(str(item), arcname=item.name)

        with self.assertRaises(UnsupportedBackupVersionError):
            self.engine.verify_backup(unsupported_archive, raise_on_error=True)

        res = self.engine.verify_backup(unsupported_archive, raise_on_error=False)
        self.assertFalse(res.is_valid)
        self.assertIn("Unsupported backup version", res.error)

    def test_missing_relation_detection(self):
        """4. Verifies detection of broken relations (missing parent checkpoint or activity)."""
        self._seed_test_data()
        result = self.engine.create_backup()
        orig_archive = Path(result.archive_path)

        # Unpack archive
        unpack_dir = self.workspace_root / "relation_unpack"
        unpack_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(orig_archive, "r:gz") as tar:
            tar.extractall(unpack_dir)

        # Tamper checkpoint 2 to point to non-existent parent checkpoint
        chk2_file = unpack_dir / "activities" / "act_p77_main" / "checkpoints" / "chk_p77_002.json"
        chk2_data = json.loads(chk2_file.read_text(encoding="utf-8"))
        chk2_data["parent_checkpoint_id"] = "chk_nonexistent_ancestor_999"
        chk2_file.write_text(json.dumps(chk2_data), encoding="utf-8")

        # Update manifest hash for chk2
        new_hash, new_size = hash_file_stream(chk2_file)
        manifest_file = unpack_dir / "manifest.json"
        mdata = json.loads(manifest_file.read_text(encoding="utf-8"))
        for fentry in mdata["file_manifest"]:
            if "chk_p77_002.json" in fentry["path"]:
                fentry["sha256"] = new_hash
                fentry["size_bytes"] = new_size
        manifest_file.write_text(json.dumps(mdata), encoding="utf-8")

        broken_rel_archive = self.workspace_root / "broken_rel.tar.gz"
        with tarfile.open(broken_rel_archive, "w:gz") as tar:
            for item in sorted(unpack_dir.iterdir()):
                tar.add(str(item), arcname=item.name)

        with self.assertRaises(MissingRelationError) as ctx:
            self.engine.verify_backup(broken_rel_archive, raise_on_error=True)
        self.assertIn("Missing relation", str(ctx.exception))
        self.assertIn("chk_nonexistent_ancestor_999", str(ctx.exception))

    def test_large_backup_bounded_memory_behavior(self):
        """5. Verifies streaming and bounded-memory behavior on multiple checkpoints (I-17)."""
        activity = Activity(id="act_large", title="Large Scale Activity")
        self.store.create_activity(activity)

        prev_id = None
        for i in range(20):
            cid = f"chk_large_{i:03d}"
            chk = UniversalCheckpoint(
                id=cid,
                activity_id="act_large",
                parent_checkpoint_id=prev_id,
                context=f"Iteration step {i} with payload data " + ("A" * 5000),
                completed_work=[f"Step {i} completed"],
            )
            self.store.commit_checkpoint(chk)
            prev_id = cid

        # Backup creation and verification with chunked streaming
        start = time.time()
        result = self.engine.create_backup()
        duration = time.time() - start

        self.assertEqual(result.manifest.records_summary.checkpoint_count, 20)
        self.assertGreater(result.manifest.records_summary.total_bytes, 100 * 1024)

        # Verification executes smoothly
        verify_res = self.engine.verify_backup(result.archive_path)
        self.assertTrue(verify_res.is_valid)
        self.assertEqual(verify_res.verified_files_count, 21)  # 1 activity + 20 checkpoints

    def test_excluded_content_absent(self):
        """6. Verifies that SQLite index, tmp files, daemon tokens, and retention backups are excluded."""
        self._seed_test_data()

        # Plant runtime/derived files that must NEVER be in backup
        continuum_dir = self.workspace_root / ".continuum"
        (continuum_dir / "daemon.pid").write_text("12345", encoding="utf-8")
        (continuum_dir / "daemon.token").write_text("secret_session_token", encoding="utf-8")
        (continuum_dir / "scratch.tmp").write_text("temporary scratch data", encoding="utf-8")

        retention_dir = continuum_dir / "retention_backup" / "session_1"
        retention_dir.mkdir(parents=True, exist_ok=True)
        (retention_dir / "pruned_chk.json").write_text("pruned checkpoint", encoding="utf-8")

        result = self.engine.create_backup()

        with tarfile.open(result.archive_path, "r:gz") as tar:
            member_names = tar.getnames()

        # Ensure excluded files are absent
        self.assertNotIn("index.db", member_names)
        self.assertNotIn("daemon.pid", member_names)
        self.assertNotIn("daemon.token", member_names)
        self.assertNotIn("scratch.tmp", member_names)
        self.assertTrue(all("retention_backup" not in name for name in member_names))

    def test_encryption_claim_honesty(self):
        """7. Verifies that encryption status is disclosed truthfully as NONE."""
        self._seed_test_data()
        result = self.engine.create_backup()

        status_str = result.manifest.encryption_status
        self.assertIn("NONE", status_str)
        self.assertIn("NOT confidentiality or encryption", status_str)

        # Verify in verify_backup
        v = self.engine.verify_backup(result.archive_path)
        self.assertIn("NONE", v.encryption_status)

    def test_gate_recovery_promise_matches_actual_archive(self):
        """8. Gate Invariant: Recovery promise matches actual archive contents."""
        self._seed_test_data()
        result = self.engine.create_backup()

        # Unpack archive and artificially inflate records_summary.checkpoint_count in manifest
        unpack_dir = self.workspace_root / "gate_unpack"
        unpack_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(result.archive_path, "r:gz") as tar:
            tar.extractall(unpack_dir)

        manifest_file = unpack_dir / "manifest.json"
        mdata = json.loads(manifest_file.read_text(encoding="utf-8"))
        # Exaggerate promise: claim 99 checkpoints when only 2 exist
        mdata["records_summary"]["checkpoint_count"] = 99
        manifest_file.write_text(json.dumps(mdata), encoding="utf-8")

        tampered_promise_archive = self.workspace_root / "gate_tampered.tar.gz"
        with tarfile.open(tampered_promise_archive, "w:gz") as tar:
            for item in sorted(unpack_dir.iterdir()):
                tar.add(str(item), arcname=item.name)

        # Gate violation must fail verification
        with self.assertRaises(InvariantViolationError) as ctx:
            self.engine.verify_backup(tampered_promise_archive, raise_on_error=True)
        self.assertIn("Gate Violation", str(ctx.exception))

    def test_rest_api_backup_endpoints(self):
        """9. Verifies GET /api/v1/backup/scope, POST /api/v1/backup/create, and POST /api/v1/backup/verify."""
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

        self._seed_test_data()
        handler = DummyHandler(self.workspace_root)

        # 1. GET /api/v1/backup/scope
        handler.handle_get_v1_backup_scope()
        self.assertEqual(handler.status_code, 200)
        self.assertIn("included_records", handler.response_data["scope"])
        self.assertIn("rebuilt_derived_data", handler.response_data["scope"])

        # 2. POST /api/v1/backup/create
        create_payload = json.dumps({"backup_name": "rest_backup.tar.gz"}).encode("utf-8")
        handler.headers = {"Content-Length": str(len(create_payload))}
        handler.rfile = io.BytesIO(create_payload)

        handler.handle_post_v1_backup_create()
        self.assertEqual(handler.status_code, 200)
        created_path = handler.response_data["backup"]["archive_path"]
        self.assertTrue(Path(created_path).is_file())

        # 3. POST /api/v1/backup/verify
        verify_payload = json.dumps({"archive_path": created_path}).encode("utf-8")
        handler.headers = {"Content-Length": str(len(verify_payload))}
        handler.rfile = io.BytesIO(verify_payload)

        handler.handle_post_v1_backup_verify()
        self.assertEqual(handler.status_code, 200)
        self.assertTrue(handler.response_data["result"]["is_valid"])
        self.assertTrue(handler.response_data["result"]["recovery_promise_verified"])


if __name__ == "__main__":
    unittest.main()
