"""
Project Continuum - Phase 51 Audit Verification Test Suite
==========================================================
Milestone 35: Repository Discovery and Baseline
Phase 51: Data, Persistence, Security and Integration Audit

Automated verification of data persistence, atomic write contracts, recovery mechanics,
CORS security, token authentication, secret redaction, path normalization, and adapter contracts.
"""

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.enums import TargetModel
from core.schema import validate_canonical_state_dict, CANONICAL_STATE_SCHEMA_VERSION
from core.serializer import CanonicalStateSerializer, StateValidationError
from core.state_models import CanonicalProjectState, ProjectState, HandoffCheckpoint
from storage.manager import ContinuumStorageManager
from storage.recovery import StateRecoveryManager
from server.auth import CorsOriginGuard, SessionAuthManager
from server.daemon import ContinuumHttpDaemon
from server.sanitizer import DaemonSanitizer
from handoff.adapters import get_adapter_for_model


class TestPhase51DataPersistenceSecurityAudit(unittest.TestCase):
    """Verifies all architectural, data durability, security, and adapter contracts."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="continuum_p51_test_")
        self.workspace = Path(self.temp_dir)
        self.storage = ContinuumStorageManager(str(self.workspace))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_schema_validation_and_rejection(self):
        """Verify schema validator enforces Draft 2020-12 / Draft-07 contracts and detects invalid payloads."""
        state = CanonicalProjectState(project_id="test_proj_p51")
        state_dict = state.to_dict()
        
        is_valid, errors = validate_canonical_state_dict(state_dict)
        self.assertTrue(is_valid, f"Canonical state must be valid: {errors}")
        
        # Corrupt required root property
        corrupted_dict = dict(state_dict)
        del corrupted_dict["project_state"]
        is_valid_corrupt, errors_corrupt = validate_canonical_state_dict(corrupted_dict)
        self.assertFalse(is_valid_corrupt, "State missing project_state must fail validation")
        self.assertTrue(any("project_state" in err for err in errors_corrupt))

    def test_atomic_file_persistence_and_snapshots(self):
        """Verify atomic state file writing and versioned history snapshot creation."""
        self.storage.initialize_storage()
        state = CanonicalProjectState(project_id="test_proj_atomic")
        
        saved_path = self.storage.save_state(state, create_history_snapshot=True, commit_tag="init")
        self.assertTrue(Path(saved_path).is_file(), "Active state file must exist")
        self.assertTrue(self.storage.state_exists(), "state_exists must return True")
        
        # Verify history snapshot was created
        snapshots = self.storage.list_history_snapshots()
        self.assertEqual(len(snapshots), 1, "Exactly one snapshot should be created")
        self.assertIn("init", snapshots[0].name)
        
        # Verify round-trip load
        loaded_state = self.storage.load_state(validate=True)
        self.assertEqual(loaded_state.project_id, "test_proj_atomic")

    def test_state_corruption_detection_and_auto_recovery(self):
        """Verify StateRecoveryManager detects corruption and restores from latest valid snapshot."""
        self.storage.initialize_storage()
        state1 = CanonicalProjectState(project_id="valid_snapshot_1")
        self.storage.save_state(state1, create_history_snapshot=True, commit_tag="snap1")
        
        # Catastrophically corrupt active state.json
        self.storage.active_state_file.write_text("{ CORRUPTED_BYTES: true, broken_json...", encoding="utf-8")
        
        recovery_mgr = StateRecoveryManager(self.storage)
        is_valid, error = recovery_mgr.verify_active_state_integrity()
        self.assertFalse(is_valid, "Corrupted state must be detected as invalid")
        self.assertIsNotNone(error)
        
        # Recover from valid snapshot
        res = recovery_mgr.recover_corrupted_state()
        self.assertTrue(res.success, f"Recovery should succeed: {res.error_message}")
        self.assertTrue(res.state_restored, "State should be marked as restored")
        
        # Active state should now be valid and match snap1
        recovered_state = self.storage.load_state(validate=True)
        self.assertEqual(recovered_state.project_id, "valid_snapshot_1")

    def test_cors_origin_whitelist_boundaries(self):
        """Verify CorsOriginGuard permits authorized AI origins and blocks unauthorized external domains."""
        self.assertTrue(CorsOriginGuard.is_origin_allowed(None), "None origin should be allowed (same-origin/CLI)")
        self.assertTrue(CorsOriginGuard.is_origin_allowed("http://localhost:8765"))
        self.assertTrue(CorsOriginGuard.is_origin_allowed("http://127.0.0.1:3000"))
        self.assertTrue(CorsOriginGuard.is_origin_allowed("https://chatgpt.com"))
        self.assertTrue(CorsOriginGuard.is_origin_allowed("https://claude.ai"))
        self.assertTrue(CorsOriginGuard.is_origin_allowed("https://gemini.google.com"))
        self.assertTrue(CorsOriginGuard.is_origin_allowed("https://chat.deepseek.com"))
        
        # Adversarial / unauthorized origins
        self.assertFalse(CorsOriginGuard.is_origin_allowed("https://evil-attacker.com"))
        self.assertFalse(CorsOriginGuard.is_origin_allowed("http://192.168.1.100:8080"))
        self.assertFalse(CorsOriginGuard.is_origin_allowed("https://phishing-chatgpt.com"))

    def test_loopback_host_security_enforcement(self):
        """Verify ContinuumHttpDaemon rejects non-loopback host bindings."""
        # Allowed loopback
        ContinuumHttpDaemon._validate_host_security("127.0.0.1")
        ContinuumHttpDaemon._validate_host_security("localhost")
        
        # Blocked external / wildcard bindings
        with self.assertRaises(ValueError):
            ContinuumHttpDaemon._validate_host_security("0.0.0.0")
        with self.assertRaises(ValueError):
            ContinuumHttpDaemon._validate_host_security("192.168.1.25")

    def test_session_token_cryptographic_verification(self):
        """Verify SessionAuthManager enforces constant-time comparison and secure generation."""
        auth = SessionAuthManager(self.workspace)
        token = auth.generate_token()
        self.assertEqual(len(token), 48, "Token must be 48 hex characters")
        
        # Constant-time verification
        self.assertTrue(auth.verify_token(token))
        self.assertFalse(auth.verify_token("invalid_token_1234567890123456789012345678"))
        self.assertFalse(auth.verify_token(None))
        
        # Revoke
        auth.revoke_token()
        self.assertIsNone(auth.get_token())
        self.assertFalse(auth.verify_token(token))

    def test_secret_redaction_and_path_normalization(self):
        """Verify DaemonSanitizer redacts secrets and normalizes host paths."""
        # High-risk files
        self.assertTrue(DaemonSanitizer.is_high_risk_file(".env"))
        self.assertTrue(DaemonSanitizer.is_high_risk_file("credentials.json"))
        self.assertTrue(DaemonSanitizer.is_high_risk_file("id_rsa"))
        self.assertTrue(DaemonSanitizer.is_high_risk_file("server.key"))
        self.assertFalse(DaemonSanitizer.is_high_risk_file("app.py"))
        
        # Secret redaction
        text_with_keys = "OpenAI: sk-123456789012345678901234567890 and AWS: AKIAIOSFODNN7EXAMPLE"
        sanitized = DaemonSanitizer.sanitize_text(text_with_keys)
        self.assertNotIn("sk-123456789012345678901234567890", sanitized)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", sanitized)
        self.assertIn("<REDACTED_OPENAI_KEY>", sanitized)
        self.assertIn("<REDACTED_AWS_KEY>", sanitized)
        
        # Path normalization
        abs_path = self.workspace / "src" / "main.py"
        norm = DaemonSanitizer.normalize_path(abs_path, self.workspace)
        self.assertEqual(norm, "src/main.py")

    def test_omni_model_adapters_contract(self):
        """Verify all model adapters implement generate_handoff and produce valid bundles."""
        state = CanonicalProjectState(project_id="test_adapter_audit")
        models = [TargetModel.CLAUDE, TargetModel.CODEX_GPT, TargetModel.GEMINI, TargetModel.LOCAL_LLM]
        
        for m in models:
            adapter = get_adapter_for_model(m)
            self.assertIsNotNone(adapter, f"Adapter for {m} must exist")
            bundle = adapter.generate_handoff(state)
            self.assertIsInstance(bundle, dict)
            self.assertIn("handoff.md", bundle, f"Adapter {m} must produce handoff.md")
            self.assertGreater(len(bundle["handoff.md"]), 0, f"Adapter {m} handoff.md must not be empty")

    def test_checkpoint_record_migration_compatibility(self):
        """Verify HandoffCheckpoint serializes and deserializes cleanly without data loss."""
        cp = HandoffCheckpoint(
            checkpoint_id="cp_test_001",
            origin_model="chatgpt",
            target_model="claude",
            timestamp="2026-10-16T12:00:00Z",
            prompt_summary="Refactored database layer",
            compressed_prompt="<context>All tests passed</context>",
            total_messages=14,
            total_code_blocks=3,
            parent_checkpoint_id="cp_test_root",
            metadata={"framework": "fastapi", "env": "prod"}
        )
        data = cp.to_dict()
        cp_restored = HandoffCheckpoint.from_dict(data)
        self.assertEqual(cp_restored.checkpoint_id, "cp_test_001")
        self.assertEqual(cp_restored.origin_model, "chatgpt")
        self.assertEqual(cp_restored.target_model, "claude")
        self.assertEqual(cp_restored.total_messages, 14)
        self.assertEqual(cp_restored.metadata.get("framework"), "fastapi")


if __name__ == "__main__":
    unittest.main()
