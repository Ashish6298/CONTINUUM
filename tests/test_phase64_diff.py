"""
Project Continuum — Phase 64 Test Suite
========================================
Milestone 39: History, Diffs, Branch and Restore
Phase 64: Checkpoint Comparison/Diffs

Validates:
1. Additions, Removals, and Changes: State, progress, completed work, pending actions, decisions, and blockers.
2. Empty and Incompatible Snapshots: Graceful handling of minimal/empty records and cross-activity incompatibility.
3. Size Bounds & Large Artifact Protection (I-17): List and text diffs are safely clamped; artifact payloads are never loaded into memory.
4. Non-Destructive Invariant (I-03): Source checkpoints on disk are 100% bit-for-bit unchanged before and after comparison.
5. Deterministic and Understandable Diff Gate: Output is byte-for-byte identical across repeated runs and human-readable.
6. REST API Endpoint Integration: Querying `/api/v1/checkpoints/compare` via GET and POST with JSON and Markdown formatting.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
import urllib.request
import urllib.error

from core.activity import Activity, ActivityType, ActivityStatus
from core.checkpoint import (
    UniversalCheckpoint,
    DecisionRecord,
    ArtifactReference,
    ProvenanceRecord,
)
from core.checkpoint_diff import (
    CheckpointDiffEngine,
    CheckpointDiffResult,
    IncompatibleCheckpointsError,
)
from server.daemon import ContinuumHttpDaemon
from storage.activity_store import ActivityCheckpointStore


class TestPhase64CheckpointDiff(unittest.TestCase):
    """Test suite for Phase 64: Checkpoint Comparison & Diff Engine."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="continuum_p64_test_")
        self.workspace_root = Path(self.temp_dir)
        self.store = ActivityCheckpointStore(self.workspace_root)
        self.engine = CheckpointDiffEngine()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_additions_removals_and_changes(self):
        """
        Verify that changed, added, and removed state, progress, work, actions,
        decisions, blockers, and notes are accurately and deterministically compared.
        """
        act = Activity.create_blank(
            title="Comparison Features Test",
            activity_type=ActivityType.CODING,
            description="Testing diff transitions",
        )
        self.store.create_activity(act)

        # Checkpoint 1 (Base)
        chk1 = UniversalCheckpoint(
            id="chk_diff_001",
            activity_id=act.id,
            timestamp="2026-05-01T10:00:00+00:00",
            progress={"percentage": 25.0},
            completed_work=["Setup repository structure"],
            pending_actions=["Implement database layer", "Configure auth middleware"],
            decisions=[
                DecisionRecord(
                    id="dec_db_01",
                    decision="Use SQLite for index storage",
                    rationale="Embedded and zero-config",
                    constraints=["Local file only"],
                )
            ],
            blockers=["Awaiting schema confirmation"],
            context="Initial architecture draft.\nNeeds review.",
            structured_state={"env": "development", "version": "1.0.0"},
            artifacts=[
                ArtifactReference(
                    name="spec.md",
                    path_or_uri="docs/spec.md",
                    size_bytes=1024,
                    checksum_sha256="aaa111",
                )
            ],
        )

        # Checkpoint 2 (Target: Work added, action completed, decision updated, blocker resolved)
        chk2 = UniversalCheckpoint(
            id="chk_diff_002",
            activity_id=act.id,
            timestamp="2026-05-01T11:30:00+00:00",
            parent_checkpoint_id="chk_diff_001",
            progress={"percentage": 65.0},
            completed_work=["Setup repository structure", "Implement database layer"],
            pending_actions=["Configure auth middleware", "Add integration tests"],
            decisions=[
                DecisionRecord(
                    id="dec_db_01",
                    decision="Use SQLite for index storage",
                    rationale="Embedded, zero-config, and WAL mode enabled",
                    constraints=["Local file only", "WAL mode enabled"],
                ),
                DecisionRecord(
                    id="dec_sec_02",
                    decision="Enforce constant-time token verification",
                    rationale="Prevent timing attacks",
                    constraints=["Zero external deps"],
                ),
            ],
            blockers=[],  # Resolved!
            context="Initial architecture draft.\nApproved by team.",
            structured_state={"env": "staging", "version": "1.0.0", "migrated": True},
            artifacts=[
                ArtifactReference(
                    name="spec.md",
                    path_or_uri="docs/spec.md",
                    size_bytes=1200,
                    checksum_sha256="bbb222",
                ),
                ArtifactReference(
                    name="schema.sql",
                    path_or_uri="db/schema.sql",
                    size_bytes=450,
                    checksum_sha256="ccc333",
                ),
            ],
        )

        result = self.engine.compare(chk1, chk2)
        self.assertTrue(result.is_compatible)
        self.assertTrue(result.has_changes)

        # Progress verification
        self.assertEqual(result.progress.percentage_before, 25.0)
        self.assertEqual(result.progress.percentage_after, 65.0)
        self.assertEqual(result.progress.percentage_delta, 40.0)

        # Completed Work
        self.assertIn("Implement database layer", result.completed_work.added)
        self.assertEqual(result.completed_work.removed, [])
        self.assertIn("Setup repository structure", result.completed_work.persisting)

        # Pending Actions (Implement database layer was cleared; Add integration tests was added)
        self.assertIn("Add integration tests", result.pending_actions.added)
        self.assertIn("Implement database layer", result.pending_actions.removed)
        self.assertIn("Configure auth middleware", result.pending_actions.persisting)

        # Decisions
        self.assertEqual(len(result.decisions.added), 1)
        self.assertEqual(result.decisions.added[0].id, "dec_sec_02")
        self.assertEqual(len(result.decisions.modified), 1)
        self.assertEqual(result.decisions.modified[0].id, "dec_db_01")
        self.assertIn("WAL mode enabled", result.decisions.modified[0].constraints_added)

        # Blockers
        self.assertIn("Awaiting schema confirmation", result.blockers.removed)
        self.assertEqual(result.blockers.added, [])

        # Context Notes (Unified diff)
        self.assertTrue(result.context_notes.has_changed)
        self.assertIn("Needs review.", result.context_notes.unified_diff)
        self.assertIn("Approved by team.", result.context_notes.unified_diff)

        # Structured State
        self.assertIn("migrated", result.structured_state.added_keys)
        self.assertIn("env", result.structured_state.changed_keys)

        # Artifacts
        self.assertEqual(len(result.artifacts.added), 1)
        self.assertEqual(result.artifacts.added[0].name, "schema.sql")
        self.assertEqual(len(result.artifacts.modified), 1)
        self.assertEqual(result.artifacts.modified[0].name, "spec.md")
        self.assertEqual(result.artifacts.modified[0].size_delta_bytes, 176)

        # High-level summary
        self.assertIn("work item", result.high_level_summary)
        self.assertIn("resolved", result.high_level_summary)

    def test_empty_and_incompatible_snapshots(self):
        """
        Verify graceful handling when comparing empty checkpoints, identical checkpoints,
        missing checkpoints, or checkpoints from different activities.
        """
        # 1. Identical Checkpoints (Zero Changes)
        chk_a = UniversalCheckpoint.create_minimal("act_same", context="Same context")
        res_same = self.engine.compare(chk_a, chk_a)
        self.assertTrue(res_same.is_compatible)
        self.assertFalse(res_same.has_changes)
        self.assertIn("No changes", res_same.high_level_summary)

        # 2. Empty Minimal Checkpoints
        chk_empty_1 = UniversalCheckpoint(id="chk_e1", activity_id="act_e")
        chk_empty_2 = UniversalCheckpoint(id="chk_e2", activity_id="act_e")
        res_empty = self.engine.compare(chk_empty_1, chk_empty_2)
        self.assertTrue(res_empty.is_compatible)
        self.assertFalse(res_empty.has_changes)

        # 3. Cross-Activity Incompatibility (Default allow_cross_activity=False)
        chk_act_1 = UniversalCheckpoint(id="chk_1", activity_id="activity_alpha")
        chk_act_2 = UniversalCheckpoint(id="chk_2", activity_id="activity_beta")
        res_incompatible = self.engine.compare(chk_act_1, chk_act_2)
        self.assertFalse(res_incompatible.is_compatible)
        self.assertIn("different activities", res_incompatible.incompatibility_reason)

        # 4. Null / Missing Checkpoint Reference
        res_none = self.engine.compare(None, chk_act_1)
        self.assertFalse(res_none.is_compatible)
        self.assertIn("missing", res_none.incompatibility_reason)

    def test_size_bounds_and_artifact_loading_prevention(self):
        """
        Invariant I-17: Output size bounds.
        Large lists and texts are clamped; artifact payloads are never loaded into memory.
        """
        bounded_engine = CheckpointDiffEngine(max_list_items=10, max_text_diff_chars=200)

        # Generate large lists of 100 items each
        list_base = [f"Base item {i:03d}" for i in range(100)]
        list_target = [f"Target item {i:03d}" for i in range(100)]

        # Generate massive context text (10,000 chars)
        huge_text_before = "Line before " * 500
        huge_text_after = "Line after " * 500

        chk_large_1 = UniversalCheckpoint(
            id="chk_lg_1",
            activity_id="act_large",
            completed_work=list_base,
            context=huge_text_before,
            artifacts=[
                ArtifactReference(
                    name="huge_file.bin",
                    path_or_uri="data/huge.bin",
                    size_bytes=500_000_000,  # 500MB
                    checksum_sha256="sha_before",
                    snapshot_content="RAW_CONTENT_THAT_SHOULD_NEVER_BE_EXPOSED" * 1000,
                )
            ],
        )

        chk_large_2 = UniversalCheckpoint(
            id="chk_lg_2",
            activity_id="act_large",
            completed_work=list_target,
            context=huge_text_after,
            artifacts=[
                ArtifactReference(
                    name="huge_file.bin",
                    path_or_uri="data/huge.bin",
                    size_bytes=500_050_000,  # +50KB
                    checksum_sha256="sha_after",
                    snapshot_content="NEW_RAW_CONTENT" * 1000,
                )
            ],
        )

        res = bounded_engine.compare(chk_large_1, chk_large_2)

        # List bounding verification
        self.assertTrue(res.completed_work.is_truncated)
        self.assertEqual(len(res.completed_work.added), 10)
        self.assertEqual(res.completed_work.total_added, 100)

        # Text bounding verification
        self.assertTrue(res.context_notes.is_truncated)
        self.assertLessEqual(len(res.context_notes.unified_diff), 300)
        self.assertIn("truncated due to size bounds (I-17)", res.context_notes.unified_diff)

        # Artifact metadata verification (payload NEVER included in diff output)
        diff_dict = res.to_dict()
        diff_json = json.dumps(diff_dict)
        self.assertNotIn("RAW_CONTENT_THAT_SHOULD_NEVER_BE_EXPOSED", diff_json)
        self.assertEqual(res.artifacts.modified[0].size_delta_bytes, 50000)

    def test_unchanged_source_checkpoints_invariant(self):
        """
        Invariant I-03: Historical viewing & comparison is read-only; normal operations
        must never mutate physical checkpoint files on disk or update metadata.
        """
        act = Activity.create_blank(
            title="Non-Destructive Diff Invariant",
            activity_type=ActivityType.WORK_TASK,
            description="Preserve source checkpoints on disk",
        )
        self.store.create_activity(act)

        chk_src_1 = UniversalCheckpoint(
            id="chk_src_01",
            activity_id=act.id,
            context="Stable snapshot 1",
            completed_work=["Step A"],
        )
        self.store.commit_checkpoint(chk_src_1)

        chk_src_2 = UniversalCheckpoint(
            id="chk_src_02",
            activity_id=act.id,
            context="Stable snapshot 2",
            completed_work=["Step A", "Step B"],
        )
        self.store.commit_checkpoint(chk_src_2)

        file1 = self.store._get_checkpoint_file(act.id, chk_src_1.id)
        file2 = self.store._get_checkpoint_file(act.id, chk_src_2.id)

        mtime1_before = file1.stat().st_mtime_ns
        mtime2_before = file2.stat().st_mtime_ns
        hash1_before = hashlib.sha256(file1.read_bytes()).hexdigest()
        hash2_before = hashlib.sha256(file2.read_bytes()).hexdigest()

        # Run comparison multiple times
        time.sleep(0.01)
        res = self.engine.compare(chk_src_1, chk_src_2)
        self.assertTrue(res.is_compatible)

        # Assert zero bytes or modification times changed
        self.assertEqual(file1.stat().st_mtime_ns, mtime1_before)
        self.assertEqual(file2.stat().st_mtime_ns, mtime2_before)
        self.assertEqual(hashlib.sha256(file1.read_bytes()).hexdigest(), hash1_before)
        self.assertEqual(hashlib.sha256(file2.read_bytes()).hexdigest(), hash2_before)

    def test_deterministic_and_understandable_diff_gate(self):
        """
        Gate Test: Diff is deterministic and understandable.
        Produces identical JSON and Markdown output across repeated executions.
        """
        chk_a = UniversalCheckpoint(
            id="chk_gate_a",
            activity_id="act_gate",
            completed_work=["Zebra task", "Alpha task"],
            pending_actions=["Beta action"],
            blockers=["Firewall issue"],
        )
        chk_b = UniversalCheckpoint(
            id="chk_gate_b",
            activity_id="act_gate",
            completed_work=["Alpha task", "Beta action", "Zebra task"],
            pending_actions=[],
            blockers=[],
        )

        # Run 5 consecutive iterations with fixed timestamp
        results = [
            self.engine.compare(chk_a, chk_b, compared_at="2026-05-01T12:00:00+00:00")
            for _ in range(5)
        ]

        json_0 = json.dumps(results[0].to_dict(), sort_keys=True)
        md_0 = results[0].markdown_diff

        for idx, r in enumerate(results[1:], start=1):
            json_i = json.dumps(r.to_dict(), sort_keys=True)
            self.assertEqual(json_0, json_i, f"Iteration {idx} JSON differs from iteration 0!")
            self.assertEqual(md_0, r.markdown_diff, f"Iteration {idx} Markdown differs from iteration 0!")

        # Verify understandable markdown output format
        self.assertIn("### 🔍 Checkpoint Comparison", md_0)
        self.assertIn("Completed Work Evolution", md_0)
        self.assertIn("[+] Added", md_0)
        self.assertIn("[✓] Resolved", md_0)

    def test_api_checkpoints_compare_endpoints(self):
        """
        Integration test: Verifies GET and POST /api/v1/checkpoints/compare
        with JSON and Markdown formatting over HTTP.
        """
        act = Activity.create_blank(
            title="REST API Checkpoint Comparison",
            activity_type=ActivityType.CODING,
            description="Testing compare endpoint",
        )
        self.store.create_activity(act)

        chk1 = UniversalCheckpoint(
            id="chk_http_1",
            activity_id=act.id,
            completed_work=["Initial init"],
            context="Start",
        )
        self.store.commit_checkpoint(chk1)

        chk2 = UniversalCheckpoint(
            id="chk_http_2",
            activity_id=act.id,
            completed_work=["Initial init", "Configured routes"],
            context="Completed routes",
        )
        self.store.commit_checkpoint(chk2)

        daemon = ContinuumHttpDaemon(
            workspace_root=str(self.workspace_root),
            host="127.0.0.1",
            default_port=8969,
        )
        status = daemon.start(run_in_background=True)
        base_url = status.server_url
        headers = {
            "X-Continuum-Token": daemon.auth_manager.get_token() or "",
            "Content-Type": "application/json",
        }

        try:
            # 1. GET /api/v1/checkpoints/compare JSON
            get_url = f"{base_url}/api/v1/checkpoints/compare?base_id={chk1.id}&target_id={chk2.id}&activity_id={act.id}"
            req_get = urllib.request.Request(get_url, headers=headers)
            with urllib.request.urlopen(req_get, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data["status"], "success")
                diff = data["diff"]
                self.assertTrue(diff["is_compatible"])
                self.assertTrue(diff["has_changes"])
                self.assertIn("Configured routes", diff["completed_work"]["added"])

            # 2. GET /api/v1/checkpoints/compare Markdown
            md_url = f"{get_url}&format=markdown"
            req_md = urllib.request.Request(md_url, headers=headers)
            with urllib.request.urlopen(req_md, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                self.assertIn("text/markdown", resp.headers.get("Content-Type", ""))
                md_text = resp.read().decode("utf-8")
                self.assertIn("### 🔍 Checkpoint Comparison", md_text)
                self.assertIn("Configured routes", md_text)

            # 3. POST /api/v1/checkpoints/compare JSON body
            post_url = f"{base_url}/api/v1/checkpoints/compare"
            post_payload = json.dumps({
                "base_id": chk1.id,
                "target_id": chk2.id,
                "activity_id": act.id,
            }).encode("utf-8")
            req_post = urllib.request.Request(post_url, data=post_payload, headers=headers, method="POST")
            with urllib.request.urlopen(req_post, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                post_data = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(post_data["diff"]["is_compatible"])

            # 4. Error testing: Missing params (HTTP 400)
            bad_url = f"{base_url}/api/v1/checkpoints/compare?base_id={chk1.id}"
            req_bad = urllib.request.Request(bad_url, headers=headers)
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req_bad, timeout=5.0)
            self.assertEqual(ctx.exception.code, 400)

            # 5. Error testing: Non-existent checkpoint (HTTP 404)
            missing_url = f"{base_url}/api/v1/checkpoints/compare?base_id=chk_non_existent&target_id={chk2.id}"
            req_missing = urllib.request.Request(missing_url, headers=headers)
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req_missing, timeout=5.0)
            self.assertEqual(ctx.exception.code, 404)

        finally:
            daemon.stop()


if __name__ == "__main__":
    unittest.main()
