"""
Phase 75 - Permissions and Integrity Validation Test Suite
===========================================================
Validates:
1. Minimum adapter permissions: Read-only access, path traversal confinement,
   denial of access to high-risk secret files.
2. Archive validation: Format, format version, size limits, member shapes,
   authoritative IDs, references, and integrity before applying changes.
3. Pre-restore validation: Verify backup before restore; disclosure that
   checksum is NOT encryption (tamper/corruption detection only).
4. Error sanitization: Errors do not leak raw sensitive payloads, tokens,
   passwords, or private keys.
5. Mutation blockage on integrity failure: Corrupt, tampered, or invalid
   archives/payloads cannot partially mutate or overwrite authoritative records.
6. Gate Invariant: Invalid input cannot partially overwrite authoritative records.
"""

from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest

from core.activity import Activity, ActivityValidationError
from core.adapters import (
    AdapterMalformedInputError,
    AdapterPayloadLimitError,
    AdapterPermissionDeniedError,
    GitIntegrationAdapter,
    RestApiIntegrationAdapter,
    WorkspaceIntegrationAdapter,
)
from core.backup import (
    CompleteBackupEngine,
    CorruptedBackupError,
    MAX_BACKUP_ARCHIVE_BYTES,
    MissingRelationError,
    OversizedBackupError,
    UnsupportedBackupVersionError,
)
from core.checkpoint import CheckpointValidationError, UniversalCheckpoint
from core.enums import ActivityType, ConflictResolutionStrategy
from core.import_engine import CompleteImportEngine, CorruptedArchiveError
from core.privacy import PrivacyManager
from storage.activity_store import ActivityCheckpointStore


class TestPhase75PermissionsAndIntegrityValidation(unittest.TestCase):
    """Exhaustive test suite for Phase 75: Permissions and Integrity Validation."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="continuum_p75_test_")
        self.workspace_root = Path(self.temp_dir)
        self.store = ActivityCheckpointStore(self.workspace_root)
        self.backup_engine = CompleteBackupEngine(self.workspace_root)
        self.import_engine = CompleteImportEngine(self.workspace_root)

        # Create sample baseline activity and checkpoint in local workspace
        self.base_act = Activity.create_blank(title="Baseline Activity", custom_id="act_base_p75")
        self.store.create_activity(self.base_act)
        self.base_chk = UniversalCheckpoint(
            id="chk_base_p75",
            activity_id=self.base_act.id,
            context="Baseline checkpoint state",
            completed_work=["Initial task"],
        )
        self.store.commit_checkpoint(self.base_chk)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_minimum_adapter_permissions_and_path_containment(self):
        """1. Verifies adapters apply least privilege and reject path traversal escaping workspace."""
        fs_adapter = WorkspaceIntegrationAdapter(self.workspace_root)

        # Normal safe file
        safe_file = self.workspace_root / "safe.txt"
        safe_file.write_text("safe content", encoding="utf-8")
        self.assertEqual(fs_adapter.read_artifact_content("safe.txt"), "safe content")

        # Path traversal escaping workspace root must be denied
        with self.assertRaises(AdapterPermissionDeniedError):
            fs_adapter.resolve_safe_path("../../../etc/passwd")

        with self.assertRaises(AdapterPermissionDeniedError):
            fs_adapter.resolve_safe_path("..\\..\\Windows\\System32")

    def test_02_access_to_high_risk_secret_files_denied(self):
        """2. Verifies adapters reject reading high-risk secret files (e.g. .env, id_rsa, secrets.json)."""
        fs_adapter = WorkspaceIntegrationAdapter(self.workspace_root)

        # Create credential files
        env_file = self.workspace_root / ".env"
        env_file.write_text("DATABASE_URL=postgres://user:pass@localhost:5432/db", encoding="utf-8")

        key_file = self.workspace_root / "id_rsa"
        key_file.write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIEogIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----", encoding="utf-8")

        # Adapter must deny read access
        with self.assertRaises(AdapterPermissionDeniedError):
            fs_adapter.read_artifact_content(".env")

        with self.assertRaises(AdapterPermissionDeniedError):
            fs_adapter.read_artifact_content("id_rsa")

    def test_03_archive_format_and_tampered_corruption_detection(self):
        """3. Verifies detection of corrupted, truncated, or tampered archives."""
        # Create a valid backup
        archive_path = self.workspace_root / "valid_backup.tar.gz"
        self.backup_engine.create_backup(output_path=archive_path)
        self.assertTrue(archive_path.is_file())

        # Corrupt the archive by flipping bytes
        corrupted_path = self.workspace_root / "corrupted_backup.tar.gz"
        raw_bytes = bytearray(archive_path.read_bytes())
        # Corrupt middle bytes
        corrupted_bytes = raw_bytes[:150] + b"\x00\xff\xee\xdd" * 20 + raw_bytes[230:]
        corrupted_path.write_bytes(corrupted_bytes)

        # Verification must raise CorruptedBackupError or return invalid
        res = self.backup_engine.verify_backup(corrupted_path, raise_on_error=False)
        self.assertFalse(res.is_valid)

        with self.assertRaises(CorruptedBackupError):
            self.backup_engine.verify_backup(corrupted_path, raise_on_error=True)

    def test_04_unsupported_version_rejection(self):
        """4. Verifies that archives with unsupported format versions are strictly rejected."""
        archive_path = self.workspace_root / "version_test.tar.gz"
        self.backup_engine.create_backup(output_path=archive_path)

        # Modify manifest inside archive to have future unsupported version
        modified_tar_path = self.workspace_root / "unsupported_version.tar.gz"
        with tarfile.open(archive_path, "r:*") as tar_in:
            manifest_f = tar_in.extractfile("manifest.json")
            manifest_data = json.loads(manifest_f.read().decode("utf-8"))
            manifest_data["format_version"] = "continuum-backup-v999.0-future"
            new_manifest_bytes = json.dumps(manifest_data).encode("utf-8")

            with tarfile.open(modified_tar_path, "w:gz") as tar_out:
                ti = tarfile.TarInfo(name="manifest.json")
                ti.size = len(new_manifest_bytes)
                tar_out.addfile(ti, BytesIO(new_manifest_bytes))
                for m in tar_in.getmembers():
                    if m.name != "manifest.json":
                        tar_out.addfile(m, tar_in.extractfile(m))

        with self.assertRaises(UnsupportedBackupVersionError):
            self.backup_engine.verify_backup(modified_tar_path, raise_on_error=True)

    def test_05_oversized_payload_and_archive_rejection(self):
        """5. Verifies oversized adapter payloads and oversized backup archives are rejected."""
        # 1. Adapter payload limit
        rest_adapter = RestApiIntegrationAdapter(self.workspace_root)
        oversized_data = {"activity_id": "act_test", "context": "A" * (rest_adapter.MAX_PAYLOAD_BYTES + 500)}
        with self.assertRaises(AdapterPayloadLimitError):
            rest_adapter.parse_and_validate_checkpoint_payload(oversized_data)

        # 2. Archive size bounds
        small_file = self.workspace_root / "small.tar.gz"
        small_file.write_bytes(b"test")
        real_stat = small_file.stat()
        from unittest.mock import patch
        class MockStat:
            st_size = MAX_BACKUP_ARCHIVE_BYTES + 1024
            st_mode = real_stat.st_mode
        with patch.object(Path, "stat", return_value=MockStat()):
            with self.assertRaises(OversizedBackupError):
                self.backup_engine.verify_backup(small_file, raise_on_error=True)

    def test_06_missing_references_and_broken_relations_blocked(self):
        """6. Verifies missing parent checkpoints or missing owning activities fail verification."""
        archive_path = self.workspace_root / "valid_backup.tar.gz"
        self.backup_engine.create_backup(output_path=archive_path)

        # Tamper archive: remove the activity file but leave checkpoint
        tampered_archive = self.workspace_root / "dangling_chk.tar.gz"
        with tarfile.open(archive_path, "r:*") as tar_in:
            with tarfile.open(tampered_archive, "w:gz") as tar_out:
                for m in tar_in.getmembers():
                    # Omit activity.json
                    if not m.name.endswith("activity.json"):
                        tar_out.addfile(m, tar_in.extractfile(m))

        with self.assertRaises(CorruptedBackupError):
            self.backup_engine.verify_backup(tampered_archive, raise_on_error=True)

    def test_07_checksum_is_not_encryption_disclosure(self):
        """7. Verifies truthful disclosure: Checksums provide integrity, not confidentiality/encryption."""
        archive_path = self.workspace_root / "backup_enc.tar.gz"
        res = self.backup_engine.create_backup(output_path=archive_path)

        # Inspect manifest and verification result
        manifest = res.manifest
        self.assertIn("NONE", manifest.encryption_status)
        self.assertIn("NOT confidentiality or encryption", manifest.encryption_status)

        v_res = self.backup_engine.verify_backup(archive_path)
        self.assertIn("NONE", v_res.encryption_status)
        self.assertIn("NOT confidentiality or encryption", v_res.encryption_status)

    def test_08_error_sanitization_does_not_leak_sensitive_payloads(self):
        """8. Verifies that errors do not leak raw sensitive payloads, tokens, or credentials."""
        rest_adapter = RestApiIntegrationAdapter(self.workspace_root)

        # 36 chars alphanumeric after ghp_
        secret_token = "ghp_1234567890abcdef1234567890abcdef1234"
        secret_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.do_not_leak"

        raw_payload = {
            "activity_id": "act_leak_test",
            "context": f"Connecting with token {secret_token} and jwt {secret_jwt}",
            "completed_work": ["Ran sync"],
        }

        # Parsing sanitizes and strips raw token from output
        chk = rest_adapter.parse_and_validate_checkpoint_payload(raw_payload)
        self.assertNotIn(secret_token, chk.context)
        self.assertIn("<REDACTED_GITHUB_TOKEN>", chk.context)
        self.assertIn("<REDACTED_JWT_TOKEN>", chk.context)

    def test_09_gate_invalid_input_cannot_partially_overwrite_records(self):
        """9. GATE INVARIANT: Invalid input cannot partially overwrite authoritative records."""
        # Record initial authoritative files and state
        act_file = self.store._get_activity_file(self.base_act.id)
        chk_file = self.store._get_checkpoint_file(self.base_act.id, self.base_chk.id)

        initial_act_mtime = act_file.stat().st_mtime
        initial_chk_content = chk_file.read_text(encoding="utf-8")

        # Attempt to import a totally corrupted archive with OVERWRITE strategy
        corrupt_tar = self.workspace_root / "corrupted_import.tar.gz"
        corrupt_tar.write_bytes(b"NOT_A_VALID_TAR_ARCHIVE_GARBAGE")

        with self.assertRaises(CorruptedArchiveError):
            self.import_engine.execute_import(
                archive_path=corrupt_tar,
                conflict_strategy=ConflictResolutionStrategy.OVERWRITE,
                confirm_overwrite=True,
            )

        # Verify authoritative records remained 100% untouched
        self.assertEqual(act_file.stat().st_mtime, initial_act_mtime)
        self.assertEqual(chk_file.read_text(encoding="utf-8"), initial_chk_content)

        # Check in store
        act_loaded = self.store.get_activity(self.base_act.id)
        self.assertEqual(act_loaded.title, "Baseline Activity")


if __name__ == "__main__":
    unittest.main()
