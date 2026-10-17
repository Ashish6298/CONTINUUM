"""
Unit and Contract Tests for Phase 82 - Error, Empty, Loading and Recovery UX.
Milestone 44: Accessibility, Performance and UX.

Covers:
1. Errors state what failed, whether data committed, and next steps without leaking secrets.
2. Confirmations explain consequences; cancellation does not mutate data.
3. Failed branch, restore, and import operations leave storage records 100% intact.
4. Empty archive and no results states are handled gracefully.
5. Storage and index failures report clean, user-safe diagnostics.
6. Accessible focus returns correctly after dialog dismissals.
7. Gate Invariant: UI and API never imply false success.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from core.activity import Activity
from core.checkpoint import UniversalCheckpoint
from core.enums import ActivityType, ActivityStatus, ConflictResolutionStrategy
from core.invariants import (
    ContinuumUserError,
    CommitFailedError,
    UnsafeRestoreError,
    ImportValidationError,
    RetentionLimitError,
    MigrationError,
)
from storage.activity_store import ActivityCheckpointStore, CheckpointNotFoundError
from core.import_engine import CompleteImportEngine, CorruptedArchiveError


class TestPhase82ErrorEmptyRecoveryUX(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="continuum_test_phase82_")
        self.workspace_root = Path(self.test_dir)
        self.continuum_dir = self.workspace_root / ".continuum"
        self.activities_dir = self.continuum_dir / "activities"
        self.activities_dir.mkdir(parents=True, exist_ok=True)

        self.store = ActivityCheckpointStore(self.workspace_root)

        # Seed initial activity and checkpoint
        act = Activity(
            id="act_001",
            title="Core Pipeline Architecture",
            activity_type=ActivityType.CODING,
            description="Initial design of payment flow",
            tags=["billing", "payments"],
        )
        self.act1 = self.store.create_activity(act)

        chk = UniversalCheckpoint(
            id="chk_001",
            activity_id=self.act1.id,
            completed_work=["Configured payment webhooks"],
            pending_actions=["Add signature verification"],
            context="Initial state snapshot",
        )
        self.chk1 = self.store.commit_checkpoint(chk)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_errors_state_what_failed_data_committed_next_steps(self):
        """
        Verifies all ContinuumUserError subclasses state what failed, whether data committed,
        and provide actionable next steps.
        """
        # 1. Base ContinuumUserError
        err1 = ContinuumUserError(
            user_message="Operation timed out",
            what_failed="Lock acquisition failed after 5000ms",
            data_committed=False,
            next_steps="Retry the operation after ensuring other processes release the workspace.",
        )
        d1 = err1.to_dict()
        self.assertEqual(d1["what_failed"], "Lock acquisition failed after 5000ms")
        self.assertFalse(d1["data_committed"])
        self.assertIn("Authoritative records remain unchanged", d1["data_committed_statement"])
        self.assertTrue(len(d1["next_steps"]) > 0)

        # 2. CommitFailedError
        err2 = CommitFailedError("Disk I/O error writing file")
        d2 = err2.to_dict()
        self.assertIn("Checkpoint commit failed", d2["what_failed"])
        self.assertFalse(d2["data_committed"])
        self.assertIn("No changes were committed", d2["next_steps"])

        # 3. UnsafeRestoreError
        err3 = UnsafeRestoreError("Checkpoint schema mismatch")
        d3 = err3.to_dict()
        self.assertIn("State restore aborted", d3["what_failed"])
        self.assertFalse(d3["data_committed"])
        self.assertIn("Existing timeline was NOT altered", d3["next_steps"])

        # 4. ImportValidationError
        err4 = ImportValidationError("Archive checksum tampered", validation_errors=["Bad sha256"])
        d4 = err4.to_dict()
        self.assertIn("Import archive pre-mutation validation failed", d4["what_failed"])
        self.assertFalse(d4["data_committed"])
        self.assertIn("retry", d4["next_steps"].lower())

    def test_errors_do_not_leak_secrets(self):
        """
        Verifies that error messages and what_failed strings redact sensitive tokens,
        passwords, AWS keys, and bearer tokens.
        """
        secret_msg = (
            "Failed connecting to server with token ghp_111122223333444455556666777788889999 "
            "and AKIAIOSFODNN7EXAMPLE using password=MySuperSecretPassword123! and Bearer eyJhbGciOiJIUzI1NiJ9.test"
        )
        err = ContinuumUserError(
            user_message=secret_msg,
            what_failed=secret_msg,
            next_steps="Contact admin with token " + secret_msg,
        )
        d = err.to_dict()

        for key in ("message", "what_failed", "next_steps"):
            val = d[key]
            self.assertNotIn("ghp_111122223333444455556666777788889999", val)
            self.assertNotIn("AKIAIOSFODNN7EXAMPLE", val)
            self.assertNotIn("MySuperSecretPassword123!", val)
            self.assertIn("<REDACTED_GITHUB_TOKEN>", val)
            self.assertIn("<REDACTED_AWS_KEY>", val)
            self.assertIn("<REDACTED>", val)

    def test_cancelled_destructive_action_does_not_mutate_data(self):
        """
        Verifies that cancelling a destructive action (like restore) leaves all records intact.
        """
        # Capture current state of the timeline
        checkpoints_before, _ = self.store.list_checkpoints(self.act1.id)
        self.assertEqual(len(checkpoints_before), 1)

        # Simulate cancellation logic in preview -> cancel workflow
        preview = self.store.preview_restore(self.chk1.id, self.act1.id)
        self.assertIsNotNone(preview)
        self.assertIn("state_change_summary", preview)
        self.assertIn("preservation_guarantee", preview)

        # When user cancels: confirm_restore is NEVER called.
        # Checkpoints after cancellation:
        checkpoints_after, _ = self.store.list_checkpoints(self.act1.id)
        self.assertEqual(len(checkpoints_after), 1)
        self.assertEqual(checkpoints_after[0].id, self.chk1.id)

    def test_failed_branch_leaves_source_timeline_intact(self):
        """
        Verifies that attempting to branch with invalid parameters or on failure does not mutate source.
        """
        checkpoints_before, _ = self.store.list_checkpoints(self.act1.id)

        # Attempt to branch from a non-existent checkpoint ID
        with self.assertRaises(CheckpointNotFoundError):
            self.store.branch_from_checkpoint(
                source_checkpoint_id="chk_non_existent",
                branch_name="new_feature",
            )

        checkpoints_after, _ = self.store.list_checkpoints(self.act1.id)
        self.assertEqual(len(checkpoints_after), len(checkpoints_before))
        self.assertEqual(checkpoints_after[0].id, self.chk1.id)

    def test_failed_restore_leaves_storage_records_intact(self):
        """
        Verifies that an aborted or failed restore does not alter existing timeline history.
        """
        checkpoints_before, _ = self.store.list_checkpoints(self.act1.id)

        with self.assertRaises(CheckpointNotFoundError):
            self.store.confirm_restore(
                target_checkpoint_id="chk_missing_000",
                activity_id=self.act1.id,
            )

        checkpoints_after, _ = self.store.list_checkpoints(self.act1.id)
        self.assertEqual(len(checkpoints_after), len(checkpoints_before))

    def test_failed_import_leaves_live_records_intact(self):
        """
        Verifies that attempting to import a corrupt archive fails cleanly and leaves live records unchanged.
        """
        activities_before = self.store.list_activities()
        checkpoints_before, _ = self.store.list_checkpoints(self.act1.id)

        # Create a corrupt archive (0-byte file)
        corrupt_archive = self.workspace_root / "corrupt.tar.gz"
        corrupt_archive.write_bytes(b"")

        import_engine = CompleteImportEngine(self.workspace_root)
        with self.assertRaises(CorruptedArchiveError):
            import_engine.execute_import(corrupt_archive, conflict_strategy=ConflictResolutionStrategy.REJECT)

        # Authoritative records remain 100% unchanged
        activities_after = self.store.list_activities()
        checkpoints_after, _ = self.store.list_checkpoints(self.act1.id)
        self.assertEqual(len(activities_after), len(activities_before))
        self.assertEqual(len(checkpoints_after), len(checkpoints_before))

    def test_empty_archive_handling(self):
        """
        Verifies that an archive with zero records does not crash or corrupt existing records.
        """
        from core.backup import PortableExportEngine
        export_engine = PortableExportEngine(self.workspace_root)
        # Export empty selection
        empty_result = export_engine.export_selection(activity_ids=[])
        self.assertTrue(os.path.exists(empty_result.archive_path))
        self.assertEqual(empty_result.manifest.activity_count, 0)
        self.assertEqual(empty_result.manifest.checkpoint_count, 0)

        # Verify export integrity
        v = export_engine.verify_export(empty_result.archive_path)
        self.assertTrue(v["is_valid"])
        self.assertEqual(v["activity_count"], 0)

    def test_search_no_results_empty_state(self):
        """
        Verifies search with unmatched criteria returns empty result list cleanly without error.
        """
        results, total = self.store.search(query="nonexistent_keyword_xyz_12345")
        self.assertEqual(total, 0)
        self.assertEqual(len(results), 0)

    def test_storage_and_index_failures_resilience(self):
        """
        Verifies that if search database encounters operational error, it handles it safely
        without corrupting authoritative JSON files.
        """
        # Patch sqlite connection cursor to simulate an OperationalError
        with patch.object(self.store, "_get_db_connection") as mock_conn:
            mock_cur = MagicMock()
            mock_cur.execute.side_effect = Exception("SQLite disk I/O failure")
            mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cur

            # Search handles database error gracefully and does not mutate filesystem
            results, total = self.store.search(query="billing")
            self.assertEqual(total, 0)
            self.assertEqual(len(results), 0)

        # Authoritative records still intact
        self.assertTrue((self.activities_dir / self.act1.id / "activity.json").exists())

    def test_focus_management_and_dialog_cancellation_contract(self):
        """
        Validates the HTML/JS contracts for focus management and cancellation:
        1. Modals declare aria-modal="true" and role="dialog".
        2. Dialogs contain explicit Cancel buttons.
        3. Dashboard CSS defines toast-error and toast-warning styles.
        """
        index_html = (Path(__file__).parents[1] / "server" / "static" / "index.html").read_text(encoding="utf-8")
        dashboard_js = (Path(__file__).parents[1] / "server" / "static" / "dashboard.js").read_text(encoding="utf-8")
        dashboard_css = (Path(__file__).parents[1] / "server" / "static" / "dashboard.css").read_text(encoding="utf-8")

        # ARIA dialog requirements
        self.assertIn('id="modalRestoreDialog"', index_html)
        self.assertIn('role="dialog"', index_html)
        self.assertIn('aria-modal="true"', index_html)
        self.assertIn('id="btnCancelRestore"', index_html)
        self.assertIn('id="btnCancelBranch"', index_html)

        # JS Focus and Cancellation Contracts
        self.assertIn('closeModalAccessible', dashboard_js)
        self.assertIn('lastFocusedElement', dashboard_js)
        self.assertIn('displayError', dashboard_js)
        self.assertIn('sanitizeTextForDisplay', dashboard_js)
        self.assertIn('Restore cancelled. No data was modified.', dashboard_js)

        # CSS Styling for Phase 82
        self.assertIn('.toast-error', dashboard_css)
        self.assertIn('.toast-warning', dashboard_css)
        self.assertIn('button[aria-busy="true"]', dashboard_css)

    def test_gate_ui_never_implies_false_success(self):
        """
        GATE INVARIANT:
        UI and backend never imply false success. Failed or cancelled actions
        return error responses or explicit cancellation indicators, never success status.
        """
        from server.routes import ContinuumApiHandler
        handler = ContinuumApiHandler.__new__(ContinuumApiHandler)
        handler.workspace_root = self.workspace_root

        # Mock send_response / send_header / wfile
        sent_payloads = []
        def mock_send_json(data, status_code=200):
            sent_payloads.append((data, status_code))
        handler._send_json_response = mock_send_json

        # 1. Trigger error response
        handler._send_error_response(
            message="Restore checkpoint aborted due to incompatibility",
            status_code=400,
            what_failed="Target checkpoint does not match schema version",
            data_committed=False,
            next_steps="Select a compatible historical checkpoint.",
        )

        self.assertEqual(len(sent_payloads), 1)
        err_data, code = sent_payloads[0]
        self.assertEqual(code, 400)
        self.assertNotIn("success", err_data.get("status", "").lower())
        self.assertEqual(err_data["data_committed"], False)
        self.assertIn("Authoritative records remain unchanged", err_data["data_committed_statement"])
        self.assertEqual(err_data["what_failed"], "Target checkpoint does not match schema version")


if __name__ == "__main__":
    unittest.main()
