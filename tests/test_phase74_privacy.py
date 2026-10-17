"""
Project Continuum — Phase 74 Test Suite
========================================
Milestone 42: Retention, Privacy and Security
Phase 74: Privacy Controls and Secret Redaction

Tests:
1. Comprehensive secret redaction across known token types and evidence reporting.
2. Custom denied terms redaction across text, search, briefs, logs, exports.
3. High-risk file exclusions (built-in and custom extensions/names).
4. Settings changes, atomic persistence in `.continuum/privacy.json`, and validation.
5. Search indexing and snippets privacy propagation (including excerpt masking).
6. Index rebuild with updated privacy rules (purges newly denied content).
7. Export sanitization (excludes secrets, denylisted terms, and stripped snapshots).
8. Brief sanitization and strict AI enhancement gating.
9. Runtime log sanitization.
10. REST API endpoints (GET /config, POST /config, POST /redact).
11. Gate verification: derived data and integrations cannot bypass privacy controls.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from core.activity import Activity, ActivityStatus, ActivityType
from core.checkpoint import UniversalCheckpoint, DecisionRecord, ArtifactReference, ResumeBrief
from core.enums import ArtifactMode, ProvenanceType
from core.privacy import (
    PrivacyConfig,
    PrivacyManager,
    SecretDetectionEvidence,
    SecretRedactionResult,
    PrivacyConfigError,
)
from core.resume_generator import DeterministicResumeBriefGenerator, AiEnhancementConsent
from core.search_engine import SearchDocumentBuilder, bound_excerpt
from storage.activity_store import ActivityCheckpointStore


class TestPhase74Privacy(unittest.TestCase):
    """Exhaustive test suite for Phase 74 Privacy Controls & Secret Redaction."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="continuum_p74_")
        self.workspace_root = Path(self.test_dir)
        PrivacyManager.reset_instances()
        self.privacy_mgr = PrivacyManager.get_instance(self.workspace_root)
        self.store = ActivityCheckpointStore(self.workspace_root)

    def tearDown(self):
        PrivacyManager.reset_instances()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_secret_redaction_comprehensive(self):
        """1. Verifies redaction across all verified token formats with evidence reporting."""
        sample_text = (
            "Deploying AWS with key AKIAIOSFODNN7EXAMPLE and GitHub token "
            "ghp_1234567890abcdefghijklmnopqrstuvwxyz "
            "and OpenAI key sk-1234567890abcdefghijklmnopqrstuvwxyz123456 "
            "connecting to postgresql://admin:SuperSecretPass123@db.prod.internal:5432/main."
        )

        result = self.privacy_mgr.redact_text(sample_text)

        self.assertIsInstance(result, SecretRedactionResult)
        self.assertGreater(result.redactions_count, 0)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", result.redacted_text)
        self.assertNotIn("ghp_1234567890abcdefghijklmnopqrstuvwxyz", result.redacted_text)
        self.assertNotIn("sk-1234567890abcdefghijklmnopqrstuvwxyz123456", result.redacted_text)
        self.assertNotIn("SuperSecretPass123", result.redacted_text)
        self.assertIn("<REDACTED_AWS_KEY>", result.redacted_text)
        self.assertIn("<REDACTED_GITHUB_TOKEN>", result.redacted_text)
        self.assertIn("<REDACTED_PASSWORD>", result.redacted_text)

        # Evidence & confidence disclosure check
        self.assertIn("AWS_KEY", result.categories_found)
        self.assertIn("GITHUB_TOKEN", result.categories_found)
        self.assertIn("EVIDENCE-BASED DISCLOSURE", result.confidence_assessment)
        self.assertTrue(any(e.category == "AWS_KEY" and e.confidence == "HIGH" for e in result.evidence))

    def test_custom_denied_terms_redaction(self):
        """2. Verifies case-insensitive custom denied terms redaction."""
        config = PrivacyConfig(
            custom_denied_terms=["ProjectOmega", "InternalPayroll2026"]
        )
        self.privacy_mgr.save_config(config)

        text = "Confidential work on projectomega regarding internalpayroll2026 allocations."
        sanitized = self.privacy_mgr.sanitize_text(text)

        self.assertNotIn("projectomega", sanitized.lower())
        self.assertNotIn("internalpayroll2026", sanitized.lower())
        self.assertIn("<REDACTED_DENIED_TERM>", sanitized)

    def test_high_risk_file_exclusions(self):
        """3. Verifies detection of built-in and custom high-risk sensitive files."""
        # Standard built-ins
        self.assertTrue(self.privacy_mgr.is_high_risk_file(".env"))
        self.assertTrue(self.privacy_mgr.is_high_risk_file("config/.env.local"))
        self.assertTrue(self.privacy_mgr.is_high_risk_file("id_rsa"))
        self.assertTrue(self.privacy_mgr.is_high_risk_file("server.key"))
        self.assertTrue(self.privacy_mgr.is_high_risk_file("secrets.json"))

        # Non-sensitive files
        self.assertFalse(self.privacy_mgr.is_high_risk_file("README.md"))
        self.assertFalse(self.privacy_mgr.is_high_risk_file("src/app.py"))

        # Custom high-risk names
        config = PrivacyConfig(
            custom_high_risk_filenames=[".customvault", "private_creds.yaml"]
        )
        self.privacy_mgr.save_config(config)

        self.assertTrue(self.privacy_mgr.is_high_risk_file("private_creds.yaml"))
        self.assertTrue(self.privacy_mgr.is_high_risk_file("keys.customvault"))

    def test_settings_changes_persistence_and_validation(self):
        """4. Verifies atomic config persistence in .continuum/privacy.json and constraint validation."""
        config_file = self.workspace_root / ".continuum" / "privacy.json"

        new_config = PrivacyConfig(
            allow_excerpts=False,
            max_excerpt_chars=140,
            allow_snapshots=False,
            max_snapshot_size_bytes=256 * 1024,
            custom_denied_terms=["TopSecret"],
            ai_enhancement_allowed=False,
        )
        self.privacy_mgr.save_config(new_config)

        self.assertTrue(config_file.is_file())
        reloaded = self.privacy_mgr.load_config()
        self.assertFalse(reloaded.allow_excerpts)
        self.assertEqual(reloaded.max_excerpt_chars, 140)
        self.assertFalse(reloaded.allow_snapshots)
        self.assertIn("TopSecret", reloaded.custom_denied_terms)

        # Validation tests
        with self.assertRaises(PrivacyConfigError):
            PrivacyConfig(automation_privacy_level="invalid_mode").validate()

        with self.assertRaises(PrivacyConfigError):
            PrivacyConfig(max_excerpt_chars=5).validate()

        # Invariant: export_include_secrets is clamped if redact_sensitive_content is True
        clamped_cfg = PrivacyConfig(export_include_secrets=True, redact_sensitive_content=True)
        clamped_cfg.validate()
        self.assertFalse(clamped_cfg.export_include_secrets)

    def test_search_indexing_and_snippets_privacy_propagation(self):
        """5. Verifies that indexed search documents and search excerpts respect privacy settings."""
        # Configure privacy with custom denied term
        config = PrivacyConfig(
            allow_excerpts=True,
            max_excerpt_chars=80,
            custom_denied_terms=["SecretAlpha"],
            redact_sensitive_content=True,
        )
        self.privacy_mgr.save_config(config)

        activity = Activity(
            id="act_p74_search",
            title="Search Privacy Activity",
            description="Testing privacy propagation in search indexing",
            tags=["privacy", "fts"],
        )
        self.store.create_activity(activity)

        checkpoint = UniversalCheckpoint(
            id="chk_p74_001",
            activity_id="act_p74_search",
            context="Session discussing SecretAlpha with token sk-1234567890abcdefghijklmnopqrstuvwxyz123456.",
            completed_work=["Completed initial database audit."],
        )
        self.store.commit_checkpoint(checkpoint)

        # Search for SecretAlpha -> must return 0 results because it was redacted at index time
        results, count = self.store.search(query="SecretAlpha")
        self.assertEqual(count, 0)

        # Search for valid word "database" -> must return hit with sanitized excerpt
        results, count = self.store.search(query="database")
        self.assertEqual(count, 1)
        hit = results[0]
        self.assertNotIn("sk-1234567890", hit.description)
        self.assertNotIn("SecretAlpha", hit.description)
        self.assertLessEqual(len(hit.description), 100)

        # Disable excerpts completely
        config.allow_excerpts = False
        self.privacy_mgr.save_config(config)

        results_no_excerpt, _ = self.store.search(query="database")
        self.assertEqual(results_no_excerpt[0].snippet, "[EXCERPT REDACTED]")

    def test_index_rebuild_with_updated_privacy_rules(self):
        """6. Verifies that rebuilding search index with new privacy rules purges newly denied items."""
        activity = Activity(
            id="act_p74_rebuild",
            title="Index Rebuild Activity",
            description="Auditing ProjectValkyrie deployment pipeline",
        )
        self.store.create_activity(activity)

        checkpoint = UniversalCheckpoint(
            id="chk_p74_rebuild_01",
            activity_id="act_p74_rebuild",
            context="Detailed architectural review of ProjectValkyrie microservices.",
        )
        self.store.commit_checkpoint(checkpoint)

        # Initially, ProjectValkyrie is searchable in both activity and checkpoint
        results, count = self.store.search(query="ProjectValkyrie")
        self.assertEqual(count, 2)

        # Update privacy policy to deny ProjectValkyrie and trigger rebuild
        new_config = PrivacyConfig(
            custom_denied_terms=["ProjectValkyrie"]
        )
        self.privacy_mgr.update_config(new_config, store=self.store, rebuild_index=True)

        # After rebuild, ProjectValkyrie must be 100% absent from search index
        results_after, count_after = self.store.search(query="ProjectValkyrie")
        self.assertEqual(count_after, 0)
        self.assertEqual(len(results_after), 0)

    def test_export_sanitization_excludes_secrets_and_snapshots(self):
        """7. Verifies recursive export payload sanitization and snapshot stripping."""
        config = PrivacyConfig(
            allow_snapshots=False,
            export_include_snapshots=False,
            custom_denied_terms=["BlackOps"],
        )
        self.privacy_mgr.save_config(config)

        raw_export = {
            "activity_id": "act_export_001",
            "title": "BlackOps Mission Plan",
            "credentials": {
                "api_key": "raw_plaintext_key_12345",
                "database_url": "postgresql://usr:pwd@host:5432/db",
            },
            "artifacts": [
                {
                    "name": "audit.txt",
                    "path_or_uri": "src/audit.txt",
                    "snapshot_content": "Sensitive snapshot text",
                    "snapshot_bytes": 1024,
                },
                {
                    "name": "id_rsa",
                    "path_or_uri": ".ssh/id_rsa",
                }
            ]
        }

        sanitized_export = self.privacy_mgr.sanitize_export_data(raw_export)

        # Title sanitized
        self.assertNotIn("BlackOps", sanitized_export["title"])
        self.assertIn("<REDACTED_DENIED_TERM>", sanitized_export["title"])

        # Sensitive keys redacted
        self.assertEqual(sanitized_export["credentials"]["api_key"], "<REDACTED_SECRET>")
        self.assertEqual(sanitized_export["credentials"]["database_url"], "<REDACTED_SECRET>")

        # Snapshots stripped
        audit_art = sanitized_export["artifacts"][0]
        self.assertNotIn("snapshot_content", audit_art)
        self.assertNotIn("snapshot_bytes", audit_art)

        # High-risk file path redacted
        key_art = sanitized_export["artifacts"][1]
        self.assertEqual(key_art["path_or_uri"], "<REDACTED_HIGH_RISK_PATH>")

    def test_brief_sanitization_and_ai_gating(self):
        """8. Verifies deterministic brief generation adheres to privacy sanitization and AI gating."""
        config = PrivacyConfig(
            custom_denied_terms=["SecretPatent"],
            ai_enhancement_allowed=False,  # Explicitly declined
        )
        self.privacy_mgr.save_config(config)

        activity = Activity(id="act_brief_priv", title="Patent Research", description="Investigating SecretPatent")
        checkpoint = UniversalCheckpoint(
            id="chk_brief_priv_01",
            activity_id="act_brief_priv",
            context="Drafting claims for SecretPatent using key AKIAIOSFODNN7EXAMPLE.",
            completed_work=["Completed claims for SecretPatent."],
        )

        mock_ai_called = [False]
        def mock_ai_callback(prompt, meta):
            mock_ai_called[0] = True
            return {"purpose": "Hallucinated AI Purpose"}

        generator = DeterministicResumeBriefGenerator(ai_provider_callback=mock_ai_callback)
        consent = AiEnhancementConsent(consent_granted=True, provider_name="TestAI", model_name="test-model")

        brief = generator.generate_brief(activity, checkpoint, ai_consent=consent)

        # Brief is sanitized
        self.assertNotIn("SecretPatent", brief.purpose)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", brief.purpose)
        self.assertIn("<REDACTED_DENIED_TERM>", brief.purpose)
        self.assertIn("<REDACTED_AWS_KEY>", brief.purpose)

        # AI enhancement was blocked because ai_enhancement_allowed is False
        self.assertFalse(mock_ai_called[0])
        self.assertFalse(brief.is_ai_enhanced)

    def test_log_sanitization(self):
        """9. Verifies runtime log sanitization strips credentials."""
        log_entry = "Database connection failed for postgresql://root:P@ssw0rd123@10.0.0.1:5432/core."
        sanitized_log = self.privacy_mgr.sanitize_log(log_entry)

        self.assertNotIn("P@ssw0rd123", sanitized_log)
        self.assertIn("<REDACTED_PASSWORD>", sanitized_log)

    def test_rest_api_privacy_endpoints(self):
        """10. Verifies GET /api/v1/privacy/config and POST /api/v1/privacy/config."""
        from server.routes import ContinuumApiHandler
        import io

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

        handler = DummyHandler(self.workspace_root)

        # GET config
        handler.handle_get_v1_privacy_config()
        self.assertEqual(handler.status_code, 200)
        self.assertIn("config", handler.response_data)
        self.assertTrue(handler.response_data["config"]["redact_sensitive_content"])

        # POST config
        new_payload = {
            "allow_excerpts": True,
            "max_excerpt_chars": 150,
            "custom_denied_terms": ["RestSecret"],
            "rebuild_index": False,
        }
        body_bytes = json.dumps(new_payload).encode("utf-8")
        handler.headers = {"Content-Length": str(len(body_bytes))}
        handler.rfile = io.BytesIO(body_bytes)

        handler.handle_post_v1_privacy_config()
        self.assertEqual(handler.status_code, 200)
        self.assertEqual(handler.response_data["config"]["max_excerpt_chars"], 150)
        self.assertIn("RestSecret", handler.response_data["config"]["custom_denied_terms"])

        # POST redact
        redact_payload = {"text": "My AWS token is AKIAIOSFODNN7EXAMPLE."}
        rbody = json.dumps(redact_payload).encode("utf-8")
        handler.headers = {"Content-Length": str(len(rbody))}
        handler.rfile = io.BytesIO(rbody)

        handler.handle_post_v1_privacy_redact()
        self.assertEqual(handler.status_code, 200)
        self.assertIn("<REDACTED_AWS_KEY>", handler.response_data["result"]["redacted_text"])
        self.assertIn("AWS_KEY", handler.response_data["result"]["categories_found"])

    def test_gate_derived_data_and_integrations_cannot_bypass_privacy(self):
        """11. Gate Invariant: Derived data and integrations cannot bypass privacy controls."""
        # Setup privacy with custom denied term and credentials
        self.privacy_mgr.save_config(
            PrivacyConfig(
                custom_denied_terms=["BypassAttemptCode"],
                redact_sensitive_content=True,
                allow_excerpts=False,
            )
        )

        activity = Activity(id="act_gate", title="Gate Activity", description="Gate verification")
        self.store.create_activity(activity)

        # Checkpoint with denied term, credentials, and high-risk file
        checkpoint = UniversalCheckpoint(
            id="chk_gate_001",
            activity_id="act_gate",
            context="Attempting BypassAttemptCode with token sk-1234567890abcdefghijklmnopqrstuvwxyz123456.",
            artifacts=[
                ArtifactReference(
                    name=".env",
                    path_or_uri="config/.env",
                    mode=ArtifactMode.REFERENCE,
                ),
                ArtifactReference(
                    name="normal.py",
                    path_or_uri="src/normal.py",
                    mode=ArtifactMode.REFERENCE,
                )
            ]
        )
        self.store.commit_checkpoint(checkpoint)

        # 1. Search document derivation check
        doc = SearchDocumentBuilder.build_checkpoint_document(checkpoint, activity=activity)
        self.assertNotIn("BypassAttemptCode", doc["description"])
        self.assertNotIn("sk-1234567890", doc["description"])
        self.assertEqual(doc["description"], "[EXCERPT REDACTED]")
        self.assertNotIn(".env", doc["artifacts"])
        self.assertIn("normal.py", doc["artifacts"])

        # 2. Search query check
        res, count = self.store.search(query="BypassAttemptCode")
        self.assertEqual(count, 0)

        # 3. Resume brief derivation check
        brief = DeterministicResumeBriefGenerator().generate_brief(activity, checkpoint)
        self.assertNotIn("BypassAttemptCode", brief.purpose)
        self.assertNotIn("sk-1234567890", brief.purpose)

        # 4. Export derivation check
        export_payload = self.privacy_mgr.sanitize_export_data({
            "context": checkpoint.context,
            "secret_key": "supersecretpassword",
        })
        self.assertNotIn("BypassAttemptCode", export_payload["context"])
        self.assertEqual(export_payload["secret_key"], "<REDACTED_SECRET>")


if __name__ == "__main__":
    unittest.main()
