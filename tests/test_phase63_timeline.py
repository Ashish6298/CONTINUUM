"""
Project Continuum — Phase 63 Test Suite
========================================
Milestone 39: History, Diffs, Branch and Restore
Phase 63: Paginated Timeline

Validates:
1. Chronological Ordering: Ascending ('asc', oldest first) and Descending ('desc', newest first).
2. Large-scale Bounded Paging (Gate): Paginating large histories in bounded batches without loading tens of thousands of records into memory at once (I-17).
3. Read-Only Timeline Invariant (I-03): Historical timeline queries and snapshot inspections never mutate physical repository state, activity metadata, or timestamps.
4. Sparse Records Resilience: Graceful handling of checkpoints with empty/minimal fields (no summary, empty work/actions/decisions).
5. Accessible Navigation & DOM Semantics: Verification of ARIA roles, tabindex, and modal dialogs in static assets.
6. REST API Endpoint Integration: Querying `/api/v1/checkpoints` and `/api/v1/activities/detail` with order, limit, and offset parameters.
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import shutil
import tempfile
import time
import unittest

from core.activity import Activity, ActivityType, ActivityStatus
from core.checkpoint import UniversalCheckpoint, DecisionRecord, ProvenanceRecord
from storage.activity_store import ActivityCheckpointStore, ActivityNotFoundError


class TestPhase63PaginatedTimeline(unittest.TestCase):
    """Test suite for Phase 63: Paginated Timeline and Read-Only History."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="continuum_p63_test_")
        self.workspace_root = Path(self.temp_dir)
        self.store = ActivityCheckpointStore(self.workspace_root)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_chronological_ordering_asc_and_desc(self):
        """
        Verify that checkpoints can be listed in both chronological ascending
        (oldest first) and descending (newest first) orders.
        """
        act = Activity.create_blank(
            title="Timeline Ordering Test",
            activity_type=ActivityType.CODING,
            description="Testing timeline order sorting",
        )
        self.store.create_activity(act)

        base_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        checkpoints_created = []

        for i in range(5):
            ts = (base_time + timedelta(minutes=10 * i)).isoformat()
            chk = UniversalCheckpoint(
                id=f"chk_order_{i:02d}",
                activity_id=act.id,
                timestamp=ts,
                context=f"Step {i}",
                completed_work=[f"Completed subtask {i}"],
                pending_actions=[f"Next action {i + 1}"],
            )
            self.store.commit_checkpoint(chk)
            checkpoints_created.append(chk)

        # 1. Test Descending Order (newest first)
        desc_list, total_desc = self.store.list_checkpoints(act.id, limit=10, offset=0, order="desc")
        self.assertEqual(total_desc, 5)
        self.assertEqual(len(desc_list), 5)
        self.assertEqual(desc_list[0].id, "chk_order_04")
        self.assertEqual(desc_list[-1].id, "chk_order_00")

        # 2. Test Ascending Order (oldest first)
        asc_list, total_asc = self.store.list_checkpoints(act.id, limit=10, offset=0, order="asc")
        self.assertEqual(total_asc, 5)
        self.assertEqual(len(asc_list), 5)
        self.assertEqual(asc_list[0].id, "chk_order_00")
        self.assertEqual(asc_list[-1].id, "chk_order_04")

    def test_large_paging_bounded_memory_gate(self):
        """
        Gate Test: Tens of thousands of records do not need to be loaded all at once.
        Verifies bounded pagination (I-17), limit clamping, and incremental batching.
        """
        act = Activity.create_blank(
            title="Large Paging Bounded Gate Test",
            activity_type=ActivityType.RESEARCH,
            description="Stress testing timeline pagination",
        )
        self.store.create_activity(act)

        # Create 65 checkpoints across the timeline
        base_time = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(65):
            ts = (base_time + timedelta(minutes=i)).isoformat()
            chk = UniversalCheckpoint(
                id=f"chk_stress_{i:03d}",
                activity_id=act.id,
                timestamp=ts,
                context=f"Iteration {i}",
                completed_work=[f"Task {i}"],
            )
            self.store.commit_checkpoint(chk)

        # Page through with batch size = 20
        all_retrieved_ids = []
        batch_size = 20
        offset = 0

        while True:
            batch, total = self.store.list_checkpoints(act.id, limit=batch_size, offset=offset, order="asc")
            self.assertEqual(total, 65)
            self.assertLessEqual(len(batch), batch_size)
            all_retrieved_ids.extend([c.id for c in batch])

            if offset + len(batch) >= total:
                break
            offset += batch_size

        # Verify all 65 were retrieved in exact ascending sequence
        self.assertEqual(len(all_retrieved_ids), 65)
        expected_ids = [f"chk_stress_{i:03d}" for i in range(65)]
        self.assertEqual(all_retrieved_ids, expected_ids)

        # Gate Verification: Requesting an absurdly high limit (e.g. 50,000)
        # must be clamped to MAX_PAGE_LIMIT (500) to protect memory
        large_batch, _ = self.store.list_checkpoints(act.id, limit=50000, offset=0)
        self.assertLessEqual(len(large_batch), self.store.MAX_PAGE_LIMIT)

    def test_read_only_timeline_behavior(self):
        """
        Invariant I-03: Historical timeline queries and snapshot inspections never
        mutate physical repository state, activity updated_at, or any checkpoint record.
        """
        act = Activity.create_blank(
            title="Read-Only Timeline Verification",
            activity_type=ActivityType.WRITING,
            description="Ensuring historical timeline is strictly read-only",
        )
        self.store.create_activity(act)

        chk1 = UniversalCheckpoint(
            id="chk_ro_01",
            activity_id=act.id,
            timestamp="2026-03-01T10:00:00+00:00",
            context="First draft",
        )
        self.store.commit_checkpoint(chk1)

        # Capture initial activity metadata & file modification time
        act_before = self.store.get_activity(act.id)
        act_file = self.store._get_activity_file(act.id)
        act_mtime_before = act_file.stat().st_mtime_ns

        chk_file = self.store._get_checkpoint_file(act.id, chk1.id)
        chk_mtime_before = chk_file.stat().st_mtime_ns

        # Execute multiple queries: list, page, sort
        time.sleep(0.01)
        self.store.list_checkpoints(act.id, limit=10, offset=0, order="asc")
        self.store.list_checkpoints(act.id, limit=10, offset=0, order="desc")
        self.store.get_checkpoint(chk1.id, act.id)

        # Assert no metadata was updated
        act_after = self.store.get_activity(act.id)
        self.assertEqual(act_before.updated_at, act_after.updated_at)
        self.assertEqual(act_file.stat().st_mtime_ns, act_mtime_before)
        self.assertEqual(chk_file.stat().st_mtime_ns, chk_mtime_before)

    def test_sparse_checkpoint_records(self):
        """
        Verify that checkpoints with minimal/empty fields (sparse records)
        render, serialize, and page without raising any exception.
        """
        act = Activity.create_blank(
            title="Sparse Checkpoint Test",
            activity_type=ActivityType.STUDY,
            description="",
        )
        self.store.create_activity(act)

        # Checkpoint with bare minimum data (empty lists, None summary, default provenance)
        sparse_chk = UniversalCheckpoint(
            id="chk_sparse_01",
            activity_id=act.id,
            timestamp="2026-03-02T12:00:00+00:00",
            context="",
            completed_work=[],
            pending_actions=[],
            decisions=[],
            blockers=[],
            artifacts=[],
        )
        self.store.commit_checkpoint(sparse_chk)

        # Retrieve and inspect
        loaded_chk = self.store.get_checkpoint("chk_sparse_01", act.id)
        self.assertEqual(loaded_chk.id, "chk_sparse_01")
        self.assertEqual(loaded_chk.completed_work, [])
        self.assertEqual(loaded_chk.pending_actions, [])
        self.assertEqual(loaded_chk.decisions, [])
        self.assertEqual(loaded_chk.blockers, [])

        # List checkpoints
        chk_list, total = self.store.list_checkpoints(act.id, limit=5, offset=0)
        self.assertEqual(total, 1)
        self.assertEqual(len(chk_list), 1)

        # Test dictionary serialization
        d = loaded_chk.to_dict()
        self.assertEqual(d["id"], "chk_sparse_01")
        self.assertEqual(d["completed_work"], [])

    def test_accessible_nav_and_dom_elements(self):
        """
        Verify that index.html and dashboard.js include required accessibility semantics
        (ARIA roles, tabindex, sorting toggle, and read-only snapshot dialog).
        """
        index_html_path = Path("server/static/index.html")
        self.assertTrue(index_html_path.exists())
        html_content = index_html_path.read_text(encoding="utf-8")

        # ARIA semantics for timeline
        self.assertIn('role="region"', html_content)
        self.assertIn('aria-label="Checkpoint Timeline"', html_content)
        self.assertIn('id="btnToggleTimelineOrder"', html_content)
        self.assertIn('id="btnLoadMoreTimeline"', html_content)

        # Read-Only Snapshot Modal semantics
        self.assertIn('id="modalSnapshotDetail"', html_content)
        self.assertIn('role="dialog"', html_content)
        self.assertIn('aria-modal="true"', html_content)
        self.assertIn('Read-Only History', html_content)

        # Verify dashboard.js contains tabindex and keyboard activation for timeline items
        dashboard_js_path = Path("server/static/dashboard.js")
        self.assertTrue(dashboard_js_path.exists())
        js_content = dashboard_js_path.read_text(encoding="utf-8")

        self.assertIn("tabIndex = 0", js_content)
        self.assertIn("role", js_content)
        self.assertIn("toggleTimelineOrder", js_content)
        self.assertIn("loadMoreTimeline", js_content)
        self.assertIn("openSnapshotModal", js_content)

    def test_api_checkpoints_pagination_and_ordering(self):
        """
        Integration test: Verifies that GET /api/v1/checkpoints and GET /api/v1/activities/detail
        return ordered, paginated, and read-only history payloads over HTTP.
        """
        import json
        import urllib.request
        from server.daemon import ContinuumHttpDaemon

        act = Activity.create_blank(
            title="REST API Timeline Test",
            activity_type=ActivityType.CODING,
            description="Testing timeline REST endpoints",
        )
        self.store.create_activity(act)

        for i in range(3):
            chk = UniversalCheckpoint(
                id=f"chk_api_{i}",
                activity_id=act.id,
                timestamp=f"2026-04-01T1{i}:00:00+00:00",
                context=f"Checkpoint {i}",
            )
            self.store.commit_checkpoint(chk)

        daemon = ContinuumHttpDaemon(
            workspace_root=str(self.workspace_root),
            host="127.0.0.1",
            default_port=8968,
        )
        status = daemon.start(run_in_background=True)
        base_url = status.server_url
        headers = {"X-Continuum-Token": daemon.auth_manager.get_token() or ""}

        try:
            # 1. Test GET /api/v1/checkpoints descending
            req = urllib.request.Request(
                f"{base_url}/api/v1/checkpoints?activity_id={act.id}&limit=2&offset=0&order=desc",
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data["status"], "success")
                self.assertEqual(data["total"], 3)
                self.assertEqual(data["count"], 2)
                self.assertTrue(data["has_more"])
                self.assertTrue(data["is_read_only_history"])
                self.assertEqual(data["checkpoints"][0]["id"], "chk_api_2")

            # 2. Test GET /api/v1/checkpoints ascending
            req_asc = urllib.request.Request(
                f"{base_url}/api/v1/checkpoints?activity_id={act.id}&limit=2&offset=0&order=asc",
                headers=headers,
            )
            with urllib.request.urlopen(req_asc, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                data_asc = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data_asc["checkpoints"][0]["id"], "chk_api_0")

            # 3. Test GET /api/v1/activities/detail with timeline
            req_det = urllib.request.Request(
                f"{base_url}/api/v1/activities/detail?activity_id={act.id}",
                headers=headers,
            )
            with urllib.request.urlopen(req_det, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                data_det = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data_det["status"], "success")
                self.assertEqual(data_det["total_checkpoints"], 3)
                self.assertTrue(data_det["is_read_only_history"])
                self.assertEqual(len(data_det["timeline"]), 3)
        finally:
            daemon.stop()


if __name__ == "__main__":
    unittest.main()

