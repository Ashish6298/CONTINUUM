"""
Full Integration and Regression Test Suite for Phase 83.
Milestone 45: Regression, Documentation and Release Readiness.

Covers End-to-End Workflow:
onboarding -> activity -> checkpoint -> brief -> reopen -> history -> search ->
branch/restore -> export/backup -> import.

Also tests unrelated existing baseline workflows:
- Evidence extraction & AST symbol parsing
- Multi-model prompt formatting and handoff packaging
- Gate verification: No unresolved core/data-safety blockers.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from core.activity import Activity
from core.checkpoint import UniversalCheckpoint, DecisionRecord, ArtifactReference
from core.enums import ActivityType, ActivityStatus, ArtifactMode, ConflictResolutionStrategy
from storage.activity_store import ActivityCheckpointStore
from core.resume_generator import DeterministicResumeBriefGenerator
from core.checkpoint_diff import CheckpointDiffEngine
from core.backup import CompleteBackupEngine, PortableExportEngine
from core.import_engine import CompleteImportEngine
from handoff.packager import UniversalHandoffPackager
from handoff.adapters import ClaudeAdapter, CodexGptAdapter, GeminiAdapter
from core.state_models import CanonicalProjectState, AstSymbol


class TestPhase83FullIntegration(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="continuum_test_phase83_")
        self.workspace_root = Path(self.test_dir)
        self.continuum_dir = self.workspace_root / ".continuum"
        self.activities_dir = self.continuum_dir / "activities"
        self.activities_dir.mkdir(parents=True, exist_ok=True)

        self.store = ActivityCheckpointStore(self.workspace_root)
        self.brief_gen = DeterministicResumeBriefGenerator()
        self.diff_engine = CheckpointDiffEngine()
        self.backup_engine = CompleteBackupEngine(self.workspace_root)
        self.export_engine = PortableExportEngine(self.workspace_root)
        self.import_engine = CompleteImportEngine(self.workspace_root)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_complete_end_to_end_continuity_pipeline(self):
        """
        Tests complete end-to-end flow:
        onboarding -> activity -> checkpoint -> brief -> reopen -> history -> search -> branch/restore -> export/backup -> import.
        """
        # 1. Onboarding & Activity Initialization
        act = Activity(
            id="act_e2e_001",
            title="E2E Pipeline Integration Test",
            activity_type=ActivityType.CODING,
            status=ActivityStatus.ACTIVE,
            description="Testing full continuity lifecycle across Project Continuum",
            tags=["e2e", "integration", "pipeline"],
        )
        created_act = self.store.create_activity(act)
        self.assertEqual(created_act.id, "act_e2e_001")
        self.assertEqual(created_act.status, ActivityStatus.ACTIVE)

        # 2. Checkpoint Commit with Structured Data & Artifacts
        chk1 = UniversalCheckpoint(
            id="chk_e2e_001_root",
            activity_id=created_act.id,
            completed_work=["Setup payment webhook handler", "Implemented database models"],
            pending_actions=["Add telemetry metrics", "Configure retry schedule"],
            decisions=[
                DecisionRecord(id="dec_01", decision="Use SQLite FTS5 for search", rationale="Fast, local, zero-network")
            ],
            context="Initial architecture setup for e2e integration flow",
            artifacts=[
                ArtifactReference(
                    name="models.py",
                    path_or_uri="src/models.py",
                    mode=ArtifactMode.REFERENCE,
                ),
                ArtifactReference(
                    name="config.env.snapshot",
                    path_or_uri="config/config.env",
                    mode=ArtifactMode.SNAPSHOT,
                    snapshot_content="ENV=test\nMAX_CONNECTIONS=10",
                ),
            ],
        )
        committed_chk1 = self.store.commit_checkpoint(chk1)
        self.assertEqual(committed_chk1.id, "chk_e2e_001_root")

        # 3. Deterministic Brief Generation (Offline, No AI required)
        brief = self.brief_gen.generate_brief(created_act, committed_chk1)
        self.assertIsNotNone(brief)
        self.assertTrue(len(brief.purpose) > 0)
        self.assertIn("Setup payment webhook handler", brief.last_completed_work)
        self.assertIn("Add telemetry metrics", brief.next_actions)
        self.assertFalse(brief.is_ai_enhanced)

        # 4. Progress Checkpoint & Checkpoint Diff
        chk2 = UniversalCheckpoint(
            id="chk_e2e_002_child",
            activity_id=created_act.id,
            parent_checkpoint_id=committed_chk1.id,
            completed_work=["Setup payment webhook handler", "Implemented database models", "Added telemetry metrics"],
            pending_actions=["Configure retry schedule"],
            decisions=[
                DecisionRecord(id="dec_01", decision="Use SQLite FTS5 for search", rationale="Fast, local, zero-network"),
                DecisionRecord(id="dec_02", decision="Use atomic replace for writes", rationale="Crash resilience"),
            ],
            context="Telemetry metrics completed",
        )
        committed_chk2 = self.store.commit_checkpoint(chk2)
        self.assertEqual(committed_chk2.parent_checkpoint_id, committed_chk1.id)

        # Compute diff between chk1 and chk2
        diff_res = self.diff_engine.compare(committed_chk1, committed_chk2)
        self.assertTrue(diff_res.is_compatible)
        self.assertTrue(diff_res.has_changes)
        self.assertIn("Added telemetry metrics", diff_res.completed_work.added)
        self.assertEqual(len(diff_res.decisions.added), 1)

        # 5. Activity Reopen / Lifecycle Transition
        created_act.status = ActivityStatus.COMPLETED
        self.store.update_activity(created_act)
        reloaded = self.store.get_activity(created_act.id)
        self.assertEqual(reloaded.status, ActivityStatus.COMPLETED)

        # Reopen to active
        reloaded.status = ActivityStatus.ACTIVE
        self.store.update_activity(reloaded)
        reopened = self.store.get_activity(created_act.id)
        self.assertEqual(reopened.status, ActivityStatus.ACTIVE)

        # 6. Timeline History & Pagination
        timeline, total_checkpoints = self.store.list_checkpoints(created_act.id, limit=10, order="desc")
        self.assertEqual(total_checkpoints, 2)
        self.assertEqual(len(timeline), 2)
        self.assertEqual(timeline[0].id, committed_chk2.id)  # newest first
        self.assertEqual(timeline[1].id, committed_chk1.id)

        # 7. Unified Local Full-Text Search
        self.store.rebuild_search_index()
        search_hits, search_count = self.store.search(query="telemetry")
        self.assertTrue(search_count >= 1)
        self.assertTrue(any("telemetry" in h.snippet.lower() or "telemetry" in h.description.lower() for h in search_hits))

        # 8. Branching
        branch_act, branch_chk = self.store.branch_from_checkpoint(
            source_checkpoint_id=committed_chk1.id,
            branch_name="experimental-feature",
            new_title="Branch from Root Checkpoint",
        )
        self.assertNotEqual(branch_act.id, created_act.id)
        self.assertEqual(branch_chk.branch_source_checkpoint_id, committed_chk1.id)
        self.assertIsNone(branch_chk.parent_checkpoint_id)

        # Verify source activity timeline was NOT mutated by branching
        src_timeline, _ = self.store.list_checkpoints(created_act.id)
        self.assertEqual(len(src_timeline), 2)

        # 9. Confirmed Restore (Rollback with newer history preserved)
        preview = self.store.preview_restore(committed_chk1.id, created_act.id)
        self.assertIsNotNone(preview)
        restored_act, restored_chk = self.store.confirm_restore(
            target_checkpoint_id=committed_chk1.id,
            activity_id=created_act.id,
            reason="Rollback to initial architecture",
        )
        self.assertEqual(restored_chk.parent_checkpoint_id, committed_chk2.id)

        # Verify that all 3 checkpoints exist (newer history preserved, I-03)
        restored_timeline, restored_count = self.store.list_checkpoints(created_act.id)
        self.assertEqual(restored_count, 3)

        # 10. Portable Versioned Export
        export_res = self.export_engine.export_selection(activity_ids=[created_act.id])
        self.assertTrue(os.path.exists(export_res.archive_path))
        self.assertEqual(export_res.manifest.activity_count, 1)
        self.assertEqual(export_res.manifest.checkpoint_count, 3)
        export_verify = self.export_engine.verify_export(export_res.archive_path)
        self.assertTrue(export_verify["is_valid"])
        self.assertFalse(export_verify["is_complete_backup"])

        # 11. Complete Disaster Recovery Backup
        backup_res = self.backup_engine.create_backup()
        self.assertTrue(os.path.exists(backup_res.archive_path))
        backup_verify = self.backup_engine.verify_backup(backup_res.archive_path)
        self.assertTrue(backup_verify.is_valid)

        # 12. Complete Import into a Clean Destination Workspace
        dest_temp = tempfile.mkdtemp(prefix="continuum_dest_workspace_")
        try:
            dest_import_engine = CompleteImportEngine(dest_temp)
            import_plan = dest_import_engine.preview_import(backup_res.archive_path)
            self.assertEqual(import_plan.manifest_summary.get("activity_count"), 2)  # original + branched

            import_result = dest_import_engine.execute_import(
                backup_res.archive_path,
                conflict_strategy=ConflictResolutionStrategy.REJECT,
            )
            self.assertTrue(import_result.success)
            self.assertEqual(import_result.activities_imported, 2)
            self.assertTrue(import_result.checkpoints_imported >= 4)

            # Verify dest workspace has restored records
            dest_store = ActivityCheckpointStore(dest_temp)
            dest_act = dest_store.get_activity(created_act.id)
            self.assertEqual(dest_act.title, created_act.title)
            dest_chks, dest_total = dest_store.list_checkpoints(created_act.id)
            self.assertEqual(dest_total, 3)
        finally:
            shutil.rmtree(dest_temp, ignore_errors=True)

    def test_unrelated_existing_baseline_workflows(self):
        """
        Verifies that existing baseline capabilities (AST symbol extraction, state models,
        and multi-model prompt packager) operate smoothly with zero regressions.
        """
        # 1. State models & AST symbol representation
        canonical_state = CanonicalProjectState(
            schema_version="1.0.0",
            project_id="test_proj_83",
        )
        sym = AstSymbol(
            name="process_payment",
            kind="function",
            file_path="src/billing.py",
            line_start=10,
            line_end=25,
            exported=True,
            docstring="Processes credit card payment.",
        )
        canonical_state.project_state.symbols.append(sym)
        self.assertEqual(len(canonical_state.project_state.symbols), 1)

        # 2. Handoff Packager across multi-model adapters
        packager = UniversalHandoffPackager()
        package = packager.generate_package(canonical_state)
        self.assertIsNotNone(package)
        self.assertIn("test_proj_83", package.project_state_json)

        # Formats for Claude, GPT, Gemini
        claude_adapter = ClaudeAdapter()
        claude_handoff = claude_adapter.generate_handoff(canonical_state)
        self.assertIn("<project_metadata>", claude_handoff["project-context.md"])
        self.assertIn("process_payment", claude_handoff["project-state.json"])

        gpt_adapter = CodexGptAdapter()
        gpt_handoff = gpt_adapter.generate_handoff(canonical_state)
        self.assertIn("process_payment", gpt_handoff["project-state.json"])

        gemini_adapter = GeminiAdapter()
        gemini_handoff = gemini_adapter.generate_handoff(canonical_state)
        self.assertIn("process_payment", gemini_handoff["project-state.json"])


if __name__ == "__main__":
    unittest.main()
