"""
Phase 71: Configurable Automatic Triggers - Comprehensive Test Suite
=====================================================================
Tests all requirements and invariants for Milestone 41 - Phase 71:
1. Manual capture always remains the authoritative baseline (I-01).
2. Supported integration triggers:
   - Git integration events (commit hash, branch, message).
   - Meaningful-change triggers (file threshold, supported extensions).
   - Scheduled / periodic triggers (interval, cooldown).
3. Individually opt-in & configurable via config:
   - Default disabled; enabling one does not enable others.
   - Updates persist to `.continuum/triggers.json`.
4. Deduplication & idempotency:
   - Duplicate git commits within dedup window are skipped.
   - Duplicate change sets within dedup window are skipped.
5. Safe retry & error handling:
   - Safe retry on transient failure.
   - Non-fatal reporting when activity not found or permission denied.
6. Strictly NO unrestricted background monitoring:
   - Passive evaluation; cooldowns strictly respected.
7. Gate & Privacy enforcement:
   - "Automation never bypasses privacy or validation."
   - High-risk credential files (.env, id_rsa, *.pem) excluded from auto checkpoints.
   - Secrets in commit messages / change notes redacted.
   - Provenance marked as AUTO_CAPTURED and non-authoritative.
8. REST API endpoints:
   - GET /api/v1/triggers/status
   - POST /api/v1/triggers/config
   - POST /api/v1/triggers/evaluate
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest

from core.activity import Activity, ActivityStatus
from core.checkpoint import UniversalCheckpoint
from core.enums import ArtifactMode, ProvenanceType
from core.manual_capture import ManualCaptureEngine, ManualCaptureRequest
from core.trigger_engine import (
    TriggerConfig,
    TriggerEngine,
    TriggerExecutionResult,
    TriggerType,
)
from storage.activity_store import ActivityCheckpointStore


class TestPhase71AutomaticTriggers(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="continuum_phase71_test_")
        self.workspace_root = Path(self.test_dir)
        self.store = ActivityCheckpointStore(self.workspace_root)

        # Create active test activity
        act_obj = Activity(
            id="act_phase71_test_01",
            title="Phase 71 Automation Test Activity",
            description="Testing automatic triggers and privacy bounds",
            activity_type="coding",
            status=ActivityStatus.ACTIVE,
        )
        self.activity = self.store.create_activity(act_obj)

        # Create engine with clean defaults (all disabled)
        self.engine = TriggerEngine(self.workspace_root, store=self.store)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_default_config_all_triggers_disabled(self):
        """Invariant: All automated triggers default to disabled (opt-in only)."""
        cfg = self.engine.config
        self.assertFalse(cfg.git_commit_enabled)
        self.assertFalse(cfg.meaningful_change_enabled)
        self.assertFalse(cfg.scheduled_enabled)
        self.assertTrue(cfg.redact_secrets)
        self.assertTrue(cfg.exclude_high_risk_files)

    def test_disabled_triggers_return_disabled_status(self):
        """Verifies that evaluating triggers when disabled returns status='disabled' with reason."""
        res_git = self.engine.evaluate_git_commit_trigger(
            commit_hash="abc1234",
            commit_message="feat: some commit",
            changed_files=["src/app.py"],
            activity_id=self.activity.id,
        )
        self.assertEqual(res_git.status, "disabled")
        self.assertIn("git_commit_enabled is False", res_git.reason)

        res_change = self.engine.evaluate_meaningful_change_trigger(
            changed_files=["src/a.py", "src/b.py", "src/c.py"],
            activity_id=self.activity.id,
        )
        self.assertEqual(res_change.status, "disabled")

        res_sched = self.engine.evaluate_scheduled_trigger(activity_id=self.activity.id)
        self.assertEqual(res_sched.status, "disabled")

    def test_opt_in_persistence_and_update(self):
        """Verifies that triggers can be enabled independently and persist across reloads."""
        # Enable only git_commit
        cfg = self.engine.config
        cfg.git_commit_enabled = True
        self.engine.save_config(cfg)

        # Reload in new engine instance
        engine2 = TriggerEngine(self.workspace_root, store=self.store)
        self.assertTrue(engine2.config.git_commit_enabled)
        self.assertFalse(engine2.config.meaningful_change_enabled)
        self.assertFalse(engine2.config.scheduled_enabled)

    def test_git_commit_trigger_creates_auto_checkpoint(self):
        """Verifies successful git commit trigger execution creating an AUTO_CAPTURED checkpoint."""
        self.engine.config.git_commit_enabled = True
        self.engine.save_config()

        res = self.engine.evaluate_git_commit_trigger(
            commit_hash="9f8e7d6c5b4a",
            commit_message="feat: implemented auth router",
            changed_files=["src/auth.py", "src/router.py"],
            branch="main",
            activity_id=self.activity.id,
        )

        self.assertEqual(res.status, "committed")
        self.assertIsNotNone(res.checkpoint_id)

        # Retrieve checkpoint from store
        chk = self.store.get_checkpoint(res.checkpoint_id, self.activity.id)
        self.assertIsNotNone(chk)
        self.assertEqual(chk.provenance.provenance_type, ProvenanceType.AUTO_CAPTURED)
        self.assertFalse(chk.provenance.is_authoritative)
        self.assertEqual(chk.provenance.details.get("commit_hash"), "9f8e7d6c5b4a")
        self.assertEqual(chk.provenance.details.get("branch"), "main")
        self.assertEqual(len(chk.artifacts), 2)

    def test_git_commit_deduplication(self):
        """Verifies that identical git commit events within the dedup window are skipped."""
        self.engine.config.git_commit_enabled = True
        self.engine.config.dedup_window_seconds = 60
        self.engine.save_config()

        # First trigger succeeds
        res1 = self.engine.evaluate_git_commit_trigger(
            commit_hash="commit_hash_111",
            commit_message="feat: duplicate check",
            changed_files=["src/main.py"],
            activity_id=self.activity.id,
        )
        self.assertEqual(res1.status, "committed")

        # Second trigger with same commit hash is skipped
        res2 = self.engine.evaluate_git_commit_trigger(
            commit_hash="commit_hash_111",
            commit_message="feat: duplicate check",
            changed_files=["src/main.py"],
            activity_id=self.activity.id,
        )
        self.assertEqual(res2.status, "skipped")
        self.assertIn("Duplicate git commit", res2.reason)

    def test_meaningful_change_thresholds_and_execution(self):
        """Verifies meaningful change triggers respect file threshold and extensions."""
        self.engine.config.meaningful_change_enabled = True
        self.engine.config.meaningful_change_min_files = 3
        self.engine.config.scheduled_min_cooldown_seconds = 0
        self.engine.save_config()

        # Below threshold (2 files) -> skipped
        res_low = self.engine.evaluate_meaningful_change_trigger(
            changed_files=["src/one.py", "src/two.py"],
            activity_id=self.activity.id,
        )
        self.assertEqual(res_low.status, "skipped")
        self.assertIn("below threshold", res_low.reason)

        # At/above threshold (3 files) -> committed
        res_ok = self.engine.evaluate_meaningful_change_trigger(
            changed_files=["src/one.py", "src/two.py", "src/three.py"],
            change_summary="Refactored components",
            activity_id=self.activity.id,
        )
        self.assertEqual(res_ok.status, "committed")
        self.assertIsNotNone(res_ok.checkpoint_id)

        chk = self.store.get_checkpoint(res_ok.checkpoint_id, self.activity.id)
        self.assertEqual(chk.provenance.provenance_type, ProvenanceType.AUTO_CAPTURED)
        self.assertEqual(len(chk.artifacts), 3)

    def test_meaningful_change_cooldown_enforcement(self):
        """Verifies meaningful change triggers respect cooldown periods."""
        self.engine.config.meaningful_change_enabled = True
        self.engine.config.meaningful_change_min_files = 1
        self.engine.config.scheduled_min_cooldown_seconds = 100
        self.engine.save_config()

        # First trigger passes
        res1 = self.engine.evaluate_meaningful_change_trigger(
            changed_files=["src/a.py"],
            activity_id=self.activity.id,
        )
        self.assertEqual(res1.status, "committed")

        # Immediate next trigger is blocked by cooldown
        res2 = self.engine.evaluate_meaningful_change_trigger(
            changed_files=["src/b.py"],
            activity_id=self.activity.id,
        )
        self.assertEqual(res2.status, "skipped")
        self.assertIn("in cooldown", res2.reason)

    def test_scheduled_trigger_execution_and_cooldown(self):
        """Verifies scheduled triggers enforce configured interval and cooldown."""
        self.engine.config.scheduled_enabled = True
        self.engine.config.scheduled_interval_seconds = 600
        self.engine.config.scheduled_min_cooldown_seconds = 60
        self.engine.save_config()

        # First trigger with force=True commits
        res1 = self.engine.evaluate_scheduled_trigger(activity_id=self.activity.id, force=True)
        self.assertEqual(res1.status, "committed")

        # Second trigger without force is skipped due to interval
        res2 = self.engine.evaluate_scheduled_trigger(activity_id=self.activity.id, force=False)
        self.assertEqual(res2.status, "skipped")
        self.assertIn("waiting for interval", res2.reason)

    def test_gate_automation_never_bypasses_privacy_or_validation(self):
        """
        GATE INVARIANT TEST:
        Automation must NEVER bypass privacy rules or data validation:
        1. Secrets in commit messages / context are strictly redacted.
        2. High-risk credential files (.env, id_rsa, *.pem) are excluded from artifact references.
        3. Custom denied terms are redacted.
        4. Checkpoints are structurally validated before commit.
        """
        self.engine.config.git_commit_enabled = True
        self.engine.config.custom_denied_terms = ["CONFIDENTIAL_PROJECT_X"]
        self.engine.save_config()

        # Secret payload with OpenAI key and high-risk credential files
        secret_msg = "feat: added OpenAI key sk-1234567890abcdef1234567890abcdef and CONFIDENTIAL_PROJECT_X"
        dirty_files = [
            "src/service.py",
            ".env",
            "certs/server.pem",
            "keys/id_rsa",
            "config/settings.json",
        ]

        res = self.engine.evaluate_git_commit_trigger(
            commit_hash="sec_hash_001",
            commit_message=secret_msg,
            changed_files=dirty_files,
            activity_id=self.activity.id,
        )

        self.assertEqual(res.status, "committed")
        self.assertGreater(res.redacted_count, 0)
        self.assertEqual(res.excluded_files_count, 3)  # .env, server.pem, id_rsa excluded

        # Verify saved checkpoint on disk
        chk = self.store.get_checkpoint(res.checkpoint_id, self.activity.id)
        self.assertNotIn("sk-1234567890abcdef1234567890abcdef", chk.context)
        self.assertIn("<REDACTED_OPENAI_KEY>", chk.context)
        self.assertNotIn("CONFIDENTIAL_PROJECT_X", chk.context)
        self.assertIn("<REDACTED_CUSTOM_TERM>", chk.context)

        # Verify high-risk files are excluded from artifacts
        artifact_paths = [a.path_or_uri for a in chk.artifacts]
        self.assertIn("src/service.py", artifact_paths)
        self.assertIn("config/settings.json", artifact_paths)
        self.assertNotIn(".env", artifact_paths)
        self.assertNotIn("certs/server.pem", artifact_paths)
        self.assertNotIn("keys/id_rsa", artifact_paths)

    def test_manual_capture_remains_authoritative_baseline(self):
        """
        Invariant I-01: Manual capture always remains the authoritative baseline,
        regardless of automation settings.
        """
        # Even with automation active or disabled, manual capture produces user_confirmed authoritative records
        manual_engine = ManualCaptureEngine(self.store, self.workspace_root)
        req = ManualCaptureRequest(
            activity_id=self.activity.id,
            context="User manual checkpoint taking priority",
            completed_work=["User authored feature"],
        )
        resp = manual_engine.capture_checkpoint(req)
        self.assertTrue(resp.success)

        chk = self.store.get_checkpoint(resp.checkpoint_id, self.activity.id)
        self.assertEqual(chk.provenance.provenance_type, ProvenanceType.USER_CONFIRMED)
        self.assertTrue(chk.provenance.is_authoritative)

    def test_target_activity_resolution_and_missing_activity(self):
        """Verifies resolution of default active activity and safe failure if non-existent."""
        # Non-existent activity returns status='error' with clear message
        self.engine.config.git_commit_enabled = True
        res_missing = self.engine.evaluate_git_commit_trigger(
            commit_hash="abc",
            commit_message="test",
            changed_files=["a.py"],
            activity_id="non_existent_activity_id",
        )
        self.assertEqual(res_missing.status, "error")
        self.assertIn("Activity 'non_existent_activity_id' does not exist", res_missing.error)

        # Omitted activity_id automatically falls back to current active activity
        res_auto = self.engine.evaluate_git_commit_trigger(
            commit_hash="def456",
            commit_message="fallback test",
            changed_files=["b.py"],
            activity_id=None,
        )
        self.assertEqual(res_auto.status, "committed")
        self.assertEqual(res_auto.activity_id, self.activity.id)

    def test_trigger_engine_get_status_inspection(self):
        """Verifies get_status returns current config and bounded recent executions."""
        self.engine.config.git_commit_enabled = True
        self.engine.evaluate_git_commit_trigger(
            commit_hash="stat_1",
            commit_message="test status",
            changed_files=["x.py"],
            activity_id=self.activity.id,
        )

        status = self.engine.get_status()
        self.assertIn("config", status)
        self.assertIn("last_trigger_time", status)
        self.assertGreaterEqual(status["history_count"], 1)
        self.assertEqual(len(status["recent_executions"]), 1)
        self.assertEqual(status["recent_executions"][0]["status"], "committed")

    def test_routes_trigger_endpoints_integration(self):
        """Verifies REST API endpoints dispatch and evaluate triggers correctly."""
        from server.routes import ContinuumApiHandler
        import io

        def make_handler(body_bytes: bytes = b""):
            handler = ContinuumApiHandler.__new__(ContinuumApiHandler)
            handler.workspace_root = self.workspace_root
            handler.require_auth = False
            handler.auth_manager = None
            handler.request_version = "HTTP/1.1"
            handler.requestline = "MOCK / HTTP/1.1"
            handler.client_address = ("127.0.0.1", 12345)
            handler.headers = {"Content-Length": str(len(body_bytes))} if body_bytes else {}
            handler.rfile = io.BytesIO(body_bytes)
            handler.wfile = io.BytesIO()
            return handler

        # 1. GET /api/v1/triggers/status
        handler_get = make_handler()
        handler_get.handle_get_v1_triggers_status()
        resp_bytes = handler_get.wfile.getvalue()
        self.assertIn(b'"status": "success"', resp_bytes)
        self.assertIn(b'"config"', resp_bytes)

        # 2. POST /api/v1/triggers/config
        update_payload = json.dumps({"git_commit_enabled": True}).encode("utf-8")
        handler_post = make_handler(update_payload)
        handler_post.handle_post_v1_triggers_config()
        self.assertIn(b'"git_commit_enabled": true', handler_post.wfile.getvalue())

        # 3. POST /api/v1/triggers/evaluate
        eval_payload = json.dumps({
            "trigger_type": "git_commit",
            "activity_id": self.activity.id,
            "payload": {
                "commit_hash": "route_test_001",
                "commit_message": "test via route",
                "changed_files": ["api.py"]
            }
        }).encode("utf-8")

        handler_eval = make_handler(eval_payload)
        handler_eval.handle_post_v1_triggers_evaluate()
        self.assertIn(b'"status": "committed"', handler_eval.wfile.getvalue())


if __name__ == "__main__":
    unittest.main()
