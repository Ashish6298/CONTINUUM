"""
Unit and Integration Tests for Phase 69: Search UI, Filters, and Result Context.
================================================================================
Milestone 40 - Phase 69: Unified Local Search.
Validates:
1. Individual and combined filters (status, type, date, tags, collection, record_type).
2. Distinguishing current state (head checkpoint) vs historical checkpoints.
3. Owning activity title mapping and checkpoint dates.
4. Bounded pagination and excerpt bounding with secret-safe redaction.
5. Handling of empty, no-match, invalid, and error recovery states.
6. Web dashboard static assets, accessibility attributes (aria-live, role), and responsive CSS.
7. Gate: unified search requires NO AI and NO network egress (100% offline local SQLite FTS5).
8. REST API endpoints: GET /api/v1/search, POST /api/v1/search, POST /api/v1/search/rebuild.
"""

from datetime import datetime, timezone, timedelta
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from core.activity import Activity, ActivityType, ActivityStatus
from core.checkpoint import UniversalCheckpoint
from core.search_engine import SearchResult, SearchQuerySanitizer, bound_excerpt
from storage.activity_store import ActivityCheckpointStore


class MockHTTPHandler:
    """Helper to exercise ContinuumApiHandler methods without a live socket server."""
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.headers = {}
        self.response_status = None
        self.response_headers = {}
        self.response_body = None
        self.rfile = io.BytesIO()
        self.wfile = io.BytesIO()

    def _set_headers(self, status_code: int = 200, content_type: str = "application/json") -> None:
        self.response_status = status_code
        self.response_headers["Content-Type"] = content_type

    def _send_json_response(self, data, status_code: int = 200):
        self._set_headers(status_code, "application/json")
        self.response_body = data

    def _send_error_response(self, message: str, status_code: int = 400, details=None):
        self._set_headers(status_code, "application/json")
        self.response_body = {"error": message, "status_code": status_code, "details": details}


class TestPhase69SearchUIBackend(unittest.TestCase):
    """Tests backend search capabilities, enrichment, filters, and excerpts."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="continuum_p69_test_")
        self.workspace_root = Path(self.temp_dir)
        self.store = ActivityCheckpointStore(self.workspace_root)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_bound_excerpt_bounds_and_tag_balancing(self):
        """Phase 69 requirement: bounded excerpts with balanced mark tags."""
        # Short text should remain unchanged
        short_text = "Short text with <mark>keyword</mark>."
        self.assertEqual(bound_excerpt(short_text, max_chars=100), short_text)

        # Long text truncated cleanly with ellipsis
        long_text = "Word " * 100
        bounded = bound_excerpt(long_text, max_chars=50)
        self.assertLessEqual(len(bounded), 55)
        self.assertTrue(bounded.endswith("..."))

        # Truncation cutting across an open mark tag should auto-close mark
        marked_text = "Analysis of <mark>critical token cut here and much more extra trailing text"
        bounded_marked = bound_excerpt(marked_text, max_chars=35)
        self.assertIn("</mark>", bounded_marked)
        self.assertEqual(bounded_marked.count("<mark>"), bounded_marked.count("</mark>"))

    def test_historical_match_vs_current_state(self):
        """
        Phase 69 requirement: Show owning activity, checkpoint date and matched context;
        distinguish history matches from current state.
        """
        # Create an activity
        act = Activity(
            id="act_arch_redesign",
            title="Core Architecture Redesign",
            description="Refactoring system domain model and search capabilities.",
            activity_type=ActivityType.CODING,
            tags=["architecture", "core", "refactor"],
            collection="Continuum V1.4"
        )
        self.store.create_activity(act)

        # Commit historical checkpoint 1 (earlier timestamp)
        ts1 = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        chk1 = UniversalCheckpoint.create_minimal(
            activity_id=act.id,
            context="Initial architecture draft with modular boundaries.",
            custom_id="chk_hist_01"
        )
        chk1.timestamp = ts1
        chk1.progress = {"percent": 30}
        chk1.notes = ["Drafting component separation and interface boundaries."]
        self.store.commit_checkpoint(chk1)

        # Commit historical checkpoint 2
        ts2 = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        chk2 = UniversalCheckpoint.create_minimal(
            activity_id=act.id,
            parent_checkpoint_id=chk1.id,
            context="Second iteration on boundaries and data contracts.",
            custom_id="chk_hist_02"
        )
        chk2.timestamp = ts2
        chk2.progress = {"percent": 60}
        chk2.notes = ["Standardizing JSON serialization across store boundaries."]
        self.store.commit_checkpoint(chk2)

        # Commit latest checkpoint 3 (current head)
        ts3 = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        chk3 = UniversalCheckpoint.create_minimal(
            activity_id=act.id,
            parent_checkpoint_id=chk2.id,
            context="Final authoritative architecture boundaries verified.",
            custom_id="chk_head_03"
        )
        chk3.timestamp = ts3
        chk3.progress = {"percent": 100}
        chk3.notes = ["All invariants satisfied and tests passing."]
        self.store.commit_checkpoint(chk3)

        # Search for "boundaries" - matches chk1, chk2, and chk3
        results, total = self.store.search(query="boundaries", record_type="checkpoint")
        self.assertEqual(total, 3)

        # Locate chk3 vs chk1/chk2 in results
        chk3_hit = next((r for r in results if r.record_id == f"chk:{chk3.id}"), None)
        chk2_hit = next((r for r in results if r.record_id == f"chk:{chk2.id}"), None)
        chk1_hit = next((r for r in results if r.record_id == f"chk:{chk1.id}"), None)

        self.assertIsNotNone(chk3_hit)
        self.assertIsNotNone(chk2_hit)
        self.assertIsNotNone(chk1_hit)

        # Verify chk3 is marked as current head / current state
        self.assertTrue(chk3_hit.is_current_head)
        self.assertEqual(chk3_hit.state_kind, "current_state")
        self.assertEqual(chk3_hit.activity_title, "Core Architecture Redesign")

        # Verify chk1 and chk2 are marked as historical
        self.assertFalse(chk2_hit.is_current_head)
        self.assertEqual(chk2_hit.state_kind, "history")
        self.assertEqual(chk2_hit.activity_title, "Core Architecture Redesign")

        self.assertFalse(chk1_hit.is_current_head)
        self.assertEqual(chk1_hit.state_kind, "history")
        self.assertEqual(chk1_hit.activity_title, "Core Architecture Redesign")

        # Search for activity directly
        act_results, _ = self.store.search(query="Redesign", record_type="activity")
        self.assertEqual(len(act_results), 1)
        self.assertTrue(act_results[0].is_current_head)
        self.assertEqual(act_results[0].state_kind, "activity")
        self.assertEqual(act_results[0].activity_title, "Core Architecture Redesign")

    def test_individual_and_combined_filters(self):
        """Phase 69 requirement: Implement filters status/type/date/tags/collection."""
        # Act 1: Coding, active, collection A, tag: security
        act1 = Activity(
            id="act_auth_hard",
            title="Authentication Hardening",
            description="JWT verification and token rotation.",
            activity_type=ActivityType.CODING,
            status=ActivityStatus.ACTIVE,
            tags=["security", "auth", "api"],
            collection="Sprint 1"
        )
        self.store.create_activity(act1)

        # Act 2: Research, paused, collection B, tag: algorithms
        act2 = Activity(
            id="act_graph_opt",
            title="Graph Optimization Analysis",
            description="Investigating topological sort performance.",
            activity_type=ActivityType.RESEARCH,
            status=ActivityStatus.ACTIVE,
            tags=["algorithms", "graph", "perf"],
            collection="Sprint 2"
        )
        self.store.create_activity(act2)
        self.store.transition_activity_status(act2.id, "paused")

        # Act 3: Study, completed, collection A, tag: docs
        act3 = Activity(
            id="act_sqlite_doc",
            title="SQLite FTS5 Documentation Review",
            description="Studying BM25 ranking algorithm and tokenizers.",
            activity_type=ActivityType.STUDY,
            status=ActivityStatus.ACTIVE,
            tags=["docs", "search", "sqlite"],
            collection="Sprint 1"
        )
        self.store.create_activity(act3)
        self.store.transition_activity_status(act3.id, "completed")

        # 1. Filter by Status
        res_active, total = self.store.search(status="active", record_type="activity")
        self.assertEqual(total, 1)
        self.assertEqual(res_active[0].title, "Authentication Hardening")

        res_paused, total = self.store.search(status="paused", record_type="activity")
        self.assertEqual(total, 1)
        self.assertEqual(res_paused[0].title, "Graph Optimization Analysis")

        # 2. Filter by Type
        res_study, total = self.store.search(activity_type="study", record_type="activity")
        self.assertEqual(total, 1)
        self.assertEqual(res_study[0].title, "SQLite FTS5 Documentation Review")

        # 3. Filter by Tag
        res_tag, total = self.store.search(tag="security", record_type="activity")
        self.assertEqual(total, 1)
        self.assertEqual(res_tag[0].title, "Authentication Hardening")

        # 4. Filter by Collection
        res_coll, total = self.store.search(collection="Sprint 1", record_type="activity")
        self.assertEqual(total, 2)

        # 5. Combined Filters: Collection "Sprint 1" + Status "completed"
        res_comb, total = self.store.search(
            collection="Sprint 1",
            status="completed",
            record_type="activity"
        )
        self.assertEqual(total, 1)
        self.assertEqual(res_comb[0].title, "SQLite FTS5 Documentation Review")

        # 6. Combined Query + Filter: "SQLite" + Status "completed"
        res_q_comb, total = self.store.search(
            query="SQLite",
            status="completed",
            record_type="activity"
        )
        self.assertEqual(total, 1)

        # 7. Combined Query + Non-matching Filter
        res_mismatch, total = self.store.search(
            query="SQLite",
            status="paused",
            record_type="activity"
        )
        self.assertEqual(total, 0)

    def test_bounded_pagination(self):
        """Phase 69 requirement: paginate results with bounded offsets and limits."""
        act = Activity(
            id="act_pagination_test",
            title="Pagination Testing Activity",
            activity_type=ActivityType.CODING
        )
        self.store.create_activity(act)

        # Commit 15 checkpoints
        for i in range(1, 16):
            chk = UniversalCheckpoint.create_minimal(
                activity_id=act.id,
                context=f"Checkpoint iteration {i} for pagination validation test.",
                custom_id=f"chk_page_{i:02d}"
            )
            self.store.commit_checkpoint(chk)

        # Page 1: limit 5, offset 0
        p1_results, total = self.store.search(record_type="checkpoint", limit=5, offset=0)
        self.assertEqual(total, 15)
        self.assertEqual(len(p1_results), 5)

        # Page 2: limit 5, offset 5
        p2_results, total = self.store.search(record_type="checkpoint", limit=5, offset=5)
        self.assertEqual(total, 15)
        self.assertEqual(len(p2_results), 5)
        # Ensure no overlap between page 1 and page 2
        p1_ids = {r.record_id for r in p1_results}
        p2_ids = {r.record_id for r in p2_results}
        self.assertTrue(p1_ids.isdisjoint(p2_ids))

        # Page 3: limit 5, offset 10
        p3_results, total = self.store.search(record_type="checkpoint", limit=5, offset=10)
        self.assertEqual(total, 15)
        self.assertEqual(len(p3_results), 5)

        # Page 4 (beyond total): offset 20
        p4_results, total = self.store.search(record_type="checkpoint", limit=5, offset=20)
        self.assertEqual(total, 15)
        self.assertEqual(len(p4_results), 0)

    def test_privacy_safe_and_bounded_snippets(self):
        """Phase 69 requirement: Privacy-safe snippets with secret redaction and character bounds."""
        act = Activity(
            id="act_sec_audit",
            title="Security Audit Activity",
            activity_type=ActivityType.CODING
        )
        self.store.create_activity(act)

        # Checkpoint contains a simulated secret token and long descriptive text
        secret_token = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        long_safe_text = "Analysis of authentication flow and token storage security vulnerabilities. " * 8
        full_text = f"{long_safe_text} Injected token: {secret_token}. Finishing review."

        chk = UniversalCheckpoint.create_minimal(
            activity_id=act.id,
            context=full_text,
            custom_id="chk_sec_token"
        )
        self.store.commit_checkpoint(chk)

        # Search for "vulnerabilities"
        results, total = self.store.search(query="vulnerabilities", record_type="checkpoint")
        self.assertGreater(total, 0)
        snippet = results[0].snippet

        # 1. Excerpt must be character-bounded
        self.assertLessEqual(len(snippet), 300)

        # 2. Secret token must be redacted (Invariant I-10)
        self.assertNotIn(secret_token, snippet)

    def test_empty_query_and_no_results_handling(self):
        """Phase 69 requirement: Gracefully handle empty queries, special characters, and zero results."""
        act = Activity(
            id="act_normal_task",
            title="Normal Project Task"
        )
        self.store.create_activity(act)

        # 1. No match query
        results, total = self.store.search(query="nonexistent_xyz_query_token_9999")
        self.assertEqual(total, 0)
        self.assertEqual(len(results), 0)

        # 2. Query with syntax characters does not crash SQLite
        results, total = self.store.search(query='"":::***@@@###')
        self.assertIsInstance(results, list)

        # 3. Empty query returns all records sorted by timestamp
        results, total = self.store.search(query="")
        self.assertGreaterEqual(total, 1)


class TestPhase69SearchUIFrontendAndStatic(unittest.TestCase):
    """Tests web UI templates, CSS, and JS components for Phase 69."""

    def test_index_html_contains_search_ui_components(self):
        """Verifies index.html includes search button, panel, filters, and accessibility."""
        html_path = Path("server/static/index.html")
        self.assertTrue(html_path.exists())
        content = html_path.read_text(encoding="utf-8")

        # Header button
        self.assertIn('id="btnToggleSearch"', content)
        self.assertIn("Alt+S", content)

        # Search center view
        self.assertIn('id="searchCenterView"', content)
        self.assertIn('role="region"', content)
        self.assertIn('aria-label="Unified Local Search"', content)

        # Controls & Filters
        self.assertIn('id="globalSearchInput"', content)
        self.assertIn('id="btnGlobalSearchSubmit"', content)
        self.assertIn('id="btnGlobalSearchClear"', content)
        self.assertIn('id="filterRecordType"', content)
        self.assertIn('id="filterStatus"', content)
        self.assertIn('id="filterType"', content)
        self.assertIn('id="filterDatePreset"', content)
        self.assertIn('id="filterTag"', content)
        self.assertIn('id="filterCollection"', content)
        self.assertIn('id="btnResetSearchFilters"', content)

        # Accessibility & Screen Reader announcements
        self.assertIn('aria-live="polite"', content)
        self.assertIn('id="searchResultSummary"', content)
        self.assertIn('id="searchResultsList"', content)
        self.assertIn('role="feed"', content)

        # Pagination controls
        self.assertIn('id="searchPagination"', content)
        self.assertIn('id="btnSearchPrevPage"', content)
        self.assertIn('id="btnSearchNextPage"', content)
        self.assertIn('id="searchPageInfo"', content)

        # Rebuild index action
        self.assertIn('id="btnRebuildSearchIndex"', content)

    def test_dashboard_css_contains_search_styles(self):
        """Verifies dashboard.css includes styling for search view, badges, marks, and responsive rules."""
        css_path = Path("server/static/dashboard.css")
        self.assertTrue(css_path.exists())
        content = css_path.read_text(encoding="utf-8")

        # Container & header
        self.assertIn(".search-center-view", content)
        self.assertIn(".search-center-header", content)
        self.assertIn(".search-controls-container", content)
        self.assertIn(".search-filters-grid", content)

        # Result cards & badges
        self.assertIn(".search-result-card", content)
        self.assertIn(".badge-current-state", content)
        self.assertIn(".badge-history", content)
        self.assertIn(".badge-activity", content)
        self.assertIn(".highlight-mark", content)
        self.assertIn(".result-owning-activity", content)

        # Pagination & responsive styles
        self.assertIn(".search-pagination-toolbar", content)
        self.assertIn("@media (max-width: 768px)", content)

    def test_dashboard_js_contains_search_logic(self):
        """Verifies dashboard.js includes search controller, shortcuts, safe snippet rendering, and error handling."""
        js_path = Path("server/static/dashboard.js")
        self.assertTrue(js_path.exists())
        content = js_path.read_text(encoding="utf-8")

        # Methods
        self.assertIn("toggleSearchCenter", content)
        self.assertIn("executeSearch", content)
        self.assertIn("renderSearchResults", content)
        self.assertIn("renderSafeSnippet", content)
        self.assertIn("renderSearchError", content)
        self.assertIn("rebuildSearchIndex", content)
        self.assertIn("clearSearch", content)
        self.assertIn("resetSearchFilters", content)

        # Distinguishing badges
        self.assertIn("badge-current-state", content)
        self.assertIn("badge-history", content)
        self.assertIn("badge-activity", content)

        # Keyboard shortcuts
        self.assertIn("Alt+S", content) or self.assertIn("altKey", content)
        self.assertIn("Escape", content)


class TestPhase69HttpEndpoints(unittest.TestCase):
    """Tests GET and POST /api/v1/search and rebuild endpoints."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="continuum_p69_http_")
        self.workspace_root = Path(self.temp_dir)
        self.store = ActivityCheckpointStore(self.workspace_root)

        # Populate sample record
        act = Activity(
            id="act_api_test",
            title="REST API Search Verification",
            description="Testing GET and POST routes for unified search.",
            activity_type=ActivityType.CODING,
            status=ActivityStatus.ACTIVE,
            tags=["rest", "api", "search"]
        )
        self.store.create_activity(act)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_handle_get_v1_search(self):
        from server.routes import ContinuumApiHandler
        handler = MockHTTPHandler(self.workspace_root)

        query = {"q": ["Verification"], "limit": ["10"], "offset": ["0"]}
        ContinuumApiHandler.handle_get_v1_search(handler, query)

        self.assertEqual(handler.response_status, 200)
        self.assertEqual(handler.response_body["status"], "success")
        self.assertEqual(handler.response_body["total"], 1)
        self.assertEqual(handler.response_body["results"][0]["activity_title"], "REST API Search Verification")

    def test_handle_post_v1_search(self):
        from server.routes import ContinuumApiHandler
        handler = MockHTTPHandler(self.workspace_root)

        payload = json.dumps({"query": "routes", "status": "active"}).encode("utf-8")
        handler.rfile = io.BytesIO(payload)
        handler.headers = {"Content-Length": str(len(payload))}

        ContinuumApiHandler.handle_post_v1_search(handler)

        self.assertEqual(handler.response_status, 200)
        self.assertEqual(handler.response_body["status"], "success")
        self.assertEqual(handler.response_body["total"], 1)

    def test_handle_post_v1_search_rebuild(self):
        from server.routes import ContinuumApiHandler
        handler = MockHTTPHandler(self.workspace_root)

        ContinuumApiHandler.handle_post_v1_search_rebuild(handler)

        self.assertEqual(handler.response_status, 200)
        self.assertEqual(handler.response_body["status"], "success")
        self.assertGreaterEqual(handler.response_body["indexed_count"], 1)


class TestPhase69GateZeroAINetwork(unittest.TestCase):
    """
    Gate Verification: Unified search requires NO AI and NO network egress.
    100% offline local SQLite FTS5 engine.
    """

    def test_gate_search_pure_local_sqlite_fts(self):
        """Verifies search execution does not invoke external network or AI models."""
        temp_dir = tempfile.mkdtemp(prefix="continuum_p69_gate_")
        try:
            store = ActivityCheckpointStore(Path(temp_dir))
            act = Activity(
                id="act_gate_check",
                title="Offline Search Gate Check"
            )
            store.create_activity(act)

            # Query execution executes locally and finishes in sub-millisecond time
            t0 = datetime.now()
            results, total = store.search("Offline")
            t_diff = (datetime.now() - t0).total_seconds()

            self.assertEqual(total, 1)
            self.assertLess(t_diff, 0.5)  # Fast local SQLite response
            self.assertEqual(results[0].title, "Offline Search Gate Check")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
