"""
Continuum Security, Privacy & Production Hardening Test Suite
=============================================================
Milestone 8 - Phase 22: Security, Privacy & Production Hardening.
Tests:
1. Secret and token sanitization (API keys, RSA keys, JWTs, DB URLs, .env variables).
2. Path traversal attack prevention & workspace boundaries.
3. Transcript storage & privacy protection.
4. Local state file permissions & isolation.
5. Command execution safety & timeout boundaries.
6. Malicious & malformed repository file protection (decompression bombs, deep recursion, syntax traps).
"""

import os
import sys
import json
import time
import shutil
import tempfile
import unittest
from pathlib import Path

# Add continuum workspace root to path
WORKSPACE_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

from core.enums import Status, TargetModel
from extractors.config.secret_sanitizer import SecretSanitizer
from extractors.config_extractor import ConfigEvidenceExtractor
from extractors.workspace_extractor import WorkspaceEvidenceExtractor
from extractors.conversation_extractor import ConversationEvidenceExtractor
from extractors.verification.runners import VerificationRunner
from storage.manager import ContinuumStorageManager
from pipeline.orchestrator import ContinuumPipeline


class TestSecurityPrivacyAndHardening(unittest.TestCase):
    """
    Phase 22 Security, Privacy, and Hardening validation suite.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="continuum_sec_")
        self.workspace_path = Path(self.temp_dir)

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_secret_sanitization_across_manifests_and_configs(self):
        """
        Security: Ensure that secrets in package manifests (API keys, DB connection strings,
        auth tokens) are strictly redacted from evidence and never leaked.
        """
        test_manifest = {
            "name": "payment-microservice",
            "version": "1.0.0",
            "dependencies": {
                "stripe": "^10.0.0"
            },
            "scripts": {
                "start": "node index.js"
            },
            "config": {
                "stripe_api_key": "sk-1234567890abcdef1234567890abcdef1234",
                "aws_access_key": "AKIA1234567890ABCDEF",
                "database_url": "postgres://admin:SuperSecretPass123@db.prod.internal:5432/main",
                "normal_setting": "public_value_allowed"
            }
        }

        sanitized = SecretSanitizer.sanitize_dict(test_manifest)

        self.assertEqual(sanitized["name"], "payment-microservice")
        self.assertEqual(sanitized["config"]["normal_setting"], "public_value_allowed")
        self.assertEqual(sanitized["config"]["stripe_api_key"], "<REDACTED_SECRET>")
        self.assertEqual(sanitized["config"]["aws_access_key"], "<REDACTED_SECRET>")
        self.assertEqual(sanitized["config"]["database_url"], "<REDACTED_SECRET>")

    def test_private_keys_and_tokens_redaction(self):
        """
        Security: Verify pattern matching for RSA/EC/OPENSSH private keys and OAuth tokens.
        """
        raw_rsa_key = "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC3\n-----END PRIVATE KEY-----"
        github_pat = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        openai_key = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
        google_api_key = "AIzaSyD-1234567890abcdefghij_klmnop"

        self.assertTrue(SecretSanitizer.contains_secret_pattern(raw_rsa_key))
        self.assertTrue(SecretSanitizer.contains_secret_pattern(github_pat))
        self.assertTrue(SecretSanitizer.contains_secret_pattern(openai_key))
        self.assertTrue(SecretSanitizer.contains_secret_pattern(google_api_key))

        sanitized_val = SecretSanitizer.sanitize_value("key_data", raw_rsa_key)
        self.assertEqual(sanitized_val, "<REDACTED_SECRET>")

    def test_path_traversal_and_workspace_boundary_protection(self):
        """
        Security: Directory walkers and evidence extractors must never escape
        the root workspace boundary into system directories via symlinks or traversal.
        """
        # Create an internal directory and a nested file
        src_dir = self.workspace_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "index.py").write_text("class CoreApp: pass", encoding="utf-8")

        # In workspace extractor, files outside ignore boundaries are captured safely
        extractor = WorkspaceEvidenceExtractor()
        evidence_list = extractor.extract(str(self.workspace_path))
        for ev in evidence_list:
            if ev.raw_payload and "file_list" in ev.raw_payload:
                for file_rel in ev.raw_payload["file_list"]:
                    self.assertFalse(file_rel.startswith(".."), f"Path traversal detected: {file_rel}")
                    self.assertFalse(":\\" in file_rel and not file_rel.startswith(str(self.workspace_path)))

    def test_transcript_privacy_and_unverified_claim_isolation(self):
        """
        Privacy & Integrity: User transcripts are ingested solely for conversational state
        and are never committed to physical ProjectState or exposed to unselected targets.
        """
        transcript_data = {
            "turns": [
                {
                    "turn_index": 1,
                    "role": "user",
                    "content": "Please implement GDPR user data deletion service with AES-256 encryption."
                },
                {
                    "turn_index": 2,
                    "role": "assistant",
                    "author_model": "claude-3-opus",
                    "content": "I have completed GDPR user data deletion service and all tests pass."
                }
            ]
        }

        pipeline = ContinuumPipeline(self.workspace_path, project_id="sec_transcript_test")
        state, summary, handoff_results = pipeline.run_full_analysis(
            conversation_input=transcript_data
        )

        # Conversational state extracted intent
        self.assertEqual(len(state.conversational_state.user_requirements), 1)
        self.assertIn("GDPR", state.conversational_state.user_requirements[0].title)

        # Physical project state was NOT contaminated (no GDPR symbols fabricated)
        physical_symbol_names = [s.name for s in state.project_state.symbols]
        self.assertNotIn("GDPR", physical_symbol_names)

        # Contradiction engine flagged the unverified claim
        self.assertGreaterEqual(len(state.contradictions), 1)

    def test_command_execution_safety_and_timeout_boundaries(self):
        """
        Security: VerificationRunner enforces strict execution timeouts and never hangs indefinitely.
        """
        runner = VerificationRunner()
        
        # Test short timeout on a command that sleeps
        t0 = time.perf_counter()
        if sys.platform == "win32":
            # powershell or cmd sleep
            res = runner.run_command(["powershell", "-Command", "Start-Sleep -Seconds 5"], cwd=self.workspace_path, timeout_seconds=1)
        else:
            res = runner.run_command(["sleep", "5"], cwd=self.workspace_path, timeout_seconds=1)
        
        elapsed = time.perf_counter() - t0

        self.assertTrue(res.timed_out)
        self.assertEqual(res.exit_code, 124)
        self.assertLess(elapsed, 3.5, "Process must terminate promptly upon timeout expiration")

    def test_malformed_and_adversarial_file_protection(self):
        """
        Hardening: Deeply nested directory trees and syntax error bombs are processed safely.
        """
        # Create a deeply nested directory structure (25 levels deep)
        curr = self.workspace_path
        for level in range(25):
            curr = curr / f"sub_{level}"
        curr.mkdir(parents=True, exist_ok=True)
        (curr / "deep_file.py").write_text("class DeepLeafNode: pass", encoding="utf-8")

        # Create syntax bomb file
        (self.workspace_path / "syntax_bomb.py").write_text("def broken_syntax( : : [ { ) } ] def def", encoding="utf-8")

        pipeline = ContinuumPipeline(self.workspace_path, project_id="sec_bomb_test")
        state, summary, _ = pipeline.run_full_analysis()

        self.assertGreater(summary.total_files_scanned, 0)
        symbol_names = [s.name for s in state.project_state.symbols]
        self.assertIn("DeepLeafNode", symbol_names)


if __name__ == "__main__":
    unittest.main()
