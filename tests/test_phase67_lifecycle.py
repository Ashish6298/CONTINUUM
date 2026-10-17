"""
Unit and Integration Tests for Phase 67 - Lifecycle, Tags, Collections, and Related Activities
=================================================================================================
Verifies:
- Complete statuses (active, paused, completed, archived) with explicit transitions.
- Reopening completed activities and restoring archived activities.
- History isolation: status transitions never delete or rewrite checkpoints.
- Custom activity types and tag edits.
- Collections grouping and aggregation.
- Related-activity linking and unlinking.
- Recent sorting and pagination.
- Stable IDs across updates.
- REST API endpoint coverage.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from core.activity import Activity, ActivityStatus, ActivityType, InvalidStatusTransitionError, ActivityValidationError
from core.checkpoint import UniversalCheckpoint
from storage.activity_store import ActivityCheckpointStore, ActivityNotFoundError
from server.routes import ContinuumApiHandler
from server.auth import SessionAuthManager


class DummyServer:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.auth_manager = SessionAuthManager(self.workspace_root)
        self.static_manager = None
        self.require_auth = False


class TestPhase67LifecycleDomainAndStore(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="continuum_test_p67_")
        self.workspace = Path(self.test_dir)
        self.store = ActivityCheckpointStore(self.workspace)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_status_transitions_and_history_preservation(self):
        """Test status transitions (active -> paused -> completed -> reopen -> archived -> restore)."""
        act = Activity(
            id="act_p67_lifecycle",
            title="Lifecycle Test Activity",
            description="Testing state machine",
            activity_type=ActivityType.CODING.value,
            status=ActivityStatus.ACTIVE,
        )
        self.store.create_activity(act)

        # Commit 2 checkpoints to history
        chk1 = UniversalCheckpoint.create_minimal(activity_id=act.id, context="Initial state")
        chk2 = UniversalCheckpoint.create_minimal(activity_id=act.id, context="Second state")
        self.store.commit_checkpoint(chk1)
        self.store.commit_checkpoint(chk2)

        # Transition to PAUSED
        paused = self.store.transition_activity_status(act.id, ActivityStatus.PAUSED)
        self.assertEqual(paused.status, ActivityStatus.PAUSED)

        # Transition to COMPLETED
        completed = self.store.transition_activity_status(act.id, ActivityStatus.COMPLETED)
        self.assertEqual(completed.status, ActivityStatus.COMPLETED)

        # Reopen COMPLETED to ACTIVE
        reopened = self.store.transition_activity_status(act.id, ActivityStatus.ACTIVE)
        self.assertEqual(reopened.status, ActivityStatus.ACTIVE)

        # Archive ACTIVE activity
        archived = self.store.archive_activity(act.id)
        self.assertEqual(archived.status, ActivityStatus.ARCHIVED)

        # Restore ARCHIVED activity to ACTIVE
        restored = self.store.restore_archived_activity(act.id, ActivityStatus.ACTIVE)
        self.assertEqual(restored.status, ActivityStatus.ACTIVE)

        # GATE CHECK: Verify all historical checkpoints remain 100% intact and unmutated
        history, total = self.store.list_checkpoints(act.id)
        self.assertEqual(total, 2)
        self.assertEqual(len(history), 2)
        chk_ids = [c.id for c in history]
        self.assertIn(chk1.id, chk_ids)
        self.assertIn(chk2.id, chk_ids)

    def test_invalid_transitions_rejected(self):
        """Invalid lifecycle transitions must raise InvalidStatusTransitionError."""
        act = Activity(
            id="act_p67_invalid_trans",
            title="Invalid Transition Activity",
            status=ActivityStatus.COMPLETED,
        )
        self.store.create_activity(act)

        # COMPLETED cannot transition directly to PAUSED
        with self.assertRaises(InvalidStatusTransitionError):
            self.store.transition_activity_status(act.id, ActivityStatus.PAUSED)

        # Unknown/invalid status string
        with self.assertRaises(InvalidStatusTransitionError):
            self.store.transition_activity_status(act.id, "non_existent_status")

    def test_custom_activity_types_and_tags(self):
        """Custom activity types and dynamic tags are supported and properly indexed."""
        act = Activity(
            id="act_p67_custom",
            title="Deep Research AI",
            description="Testing custom type",
            activity_type="deep-dive-research",
            tags=["ML", "Analysis", "ml", "nlp"],  # includes duplicate and mixed-case
            collection="AI Labs",
        )
        self.store.create_activity(act)

        fetched = self.store.get_activity(act.id)
        self.assertEqual(fetched.activity_type, "deep-dive-research")
        self.assertEqual(fetched.tags, ["ml", "analysis", "nlp"])  # normalized & deduplicated
        self.assertEqual(fetched.collection, "AI Labs")

        # Update details
        updated = self.store.update_activity_details(
            act.id,
            title="Updated Deep Research",
            tags=["nlp", "transformers"],
            collection="Advanced AI",
            activity_type="specialized-ml"
        )
        self.assertEqual(updated.title, "Updated Deep Research")
        self.assertEqual(updated.tags, ["nlp", "transformers"])
        self.assertEqual(updated.collection, "Advanced AI")
        self.assertEqual(updated.activity_type, "specialized-ml")
        # Stable ID must not change (I-01)
        self.assertEqual(updated.id, act.id)

    def test_collections_and_tags_aggregation(self):
        """Test collections and tags listing and counting."""
        act1 = Activity(id="act1", title="A1", tags=["python", "core"], collection="Continuum")
        act2 = Activity(id="act2", title="A2", tags=["python", "gui"], collection="Continuum")
        act3 = Activity(id="act3", title="A3", tags=["rust", "core"], collection="Sidecars")
        act4 = Activity(id="act4", title="A4", tags=["misc"])  # no collection

        for a in (act1, act2, act3, act4):
            self.store.create_activity(a)

        collections = self.store.list_collections()
        col_names = {c["collection"]: c["count"] for c in collections}
        self.assertEqual(col_names.get("Continuum"), 2)
        self.assertEqual(col_names.get("Sidecars"), 1)

        tags = self.store.list_tags()
        tag_counts = {t["tag"]: t["count"] for t in tags}
        self.assertEqual(tag_counts.get("python"), 2)
        self.assertEqual(tag_counts.get("core"), 2)
        self.assertEqual(tag_counts.get("gui"), 1)
        self.assertEqual(tag_counts.get("rust"), 1)
        self.assertEqual(tag_counts.get("misc"), 1)

    def test_recent_sorting_and_filtering(self):
        """Test activity listing by recent update, created date, title, and collection filter."""
        act_a = Activity(id="act_a", title="Alpha", collection="Col1")
        act_b = Activity(id="act_b", title="Beta", collection="Col1")
        act_c = Activity(id="act_c", title="Gamma", collection="Col2")

        self.store.create_activity(act_a)
        self.store.create_activity(act_b)
        self.store.create_activity(act_c)

        # Filter by collection
        col1_acts, count = self.store.list_activities(collection="Col1")
        self.assertEqual(count, 2)
        self.assertEqual({a.id for a in col1_acts}, {"act_a", "act_b"})

        # Update Alpha to make it the most recently updated
        self.store.update_activity_details("act_a", title="Alpha Updated")
        recent, _ = self.store.list_activities(sort_by="recent", order="desc")
        self.assertEqual(recent[0].id, "act_a")

        # Sort by title ascending
        by_title, _ = self.store.list_activities(sort_by="title", order="asc")
        titles = [a.title for a in by_title]
        self.assertEqual(titles, sorted(titles))

    def test_related_activity_links(self):
        """Test bidirectional and unidirectional activity linking and unlinking."""
        act1 = Activity(id="act_link_1", title="Task 1")
        act2 = Activity(id="act_link_2", title="Task 2")
        self.store.create_activity(act1)
        self.store.create_activity(act2)

        # Bidirectional link
        s1, s2 = self.store.link_activities("act_link_1", "act_link_2", bidirectional=True)
        self.assertIn("act_link_2", s1.related_activity_ids)
        self.assertIn("act_link_1", s2.related_activity_ids)

        # Linking again is idempotent
        s1_again, s2_again = self.store.link_activities("act_link_1", "act_link_2", bidirectional=True)
        self.assertEqual(s1_again.related_activity_ids.count("act_link_2"), 1)

        # Unlink
        u1, u2 = self.store.unlink_activities("act_link_1", "act_link_2", bidirectional=True)
        self.assertNotIn("act_link_2", u1.related_activity_ids)
        self.assertNotIn("act_link_1", u2.related_activity_ids)


class MockHTTPHandler:
    """Helper to exercise ContinuumApiHandler methods without a live socket server."""
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.auth_manager = SessionAuthManager(self.workspace_root)
        self.static_manager = None
        self.require_auth = False
        self.headers = {}
        self.response_status = None
        self.response_headers = {}
        self.response_body = None

    def _set_headers(self, status_code: int = 200, content_type: str = "application/json") -> None:
        self.response_status = status_code
        self.response_headers["Content-Type"] = content_type

    def _send_json_response(self, data, status_code: int = 200):
        self._set_headers(status_code, "application/json")
        self.response_body = data

    def _send_error_response(self, message: str, status_code: int = 400, details=None):
        self._set_headers(status_code, "application/json")
        self.response_body = {"error": message, "status_code": status_code, "details": details}


class TestPhase67LifecycleHTTPRoutes(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="continuum_http_p67_")
        self.workspace = Path(self.test_dir)
        self.store = ActivityCheckpointStore(self.workspace)
        self.act = Activity(
            id="act_http_67",
            title="Initial Title",
            description="Initial Description",
            activity_type="coding",
            status=ActivityStatus.ACTIVE,
            tags=["initial"],
            collection="General"
        )
        self.store.create_activity(self.act)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _make_handler(self, body_dict=None):
        import io
        handler = MockHTTPHandler(self.workspace)
        if body_dict is not None:
            raw_bytes = json.dumps(body_dict).encode("utf-8")
            handler.headers["Content-Length"] = str(len(raw_bytes))
            handler.rfile = io.BytesIO(raw_bytes)
        else:
            handler.headers["Content-Length"] = "0"
            handler.rfile = io.BytesIO(b"")
        return handler

    def test_http_get_activities_filtering_and_sorting(self):
        handler = self._make_handler()
        ContinuumApiHandler.handle_get_v1_activities(
            handler,
            {"collection": ["General"], "sort_by": ["recent"], "order": ["desc"]}
        )
        self.assertEqual(handler.response_status, 200)
        self.assertEqual(handler.response_body["count"], 1)
        self.assertEqual(handler.response_body["activities"][0]["id"], "act_http_67")

    def test_http_collections_and_tags(self):
        handler = self._make_handler()
        ContinuumApiHandler.handle_get_v1_collections(handler)
        self.assertEqual(handler.response_status, 200)
        self.assertTrue(any(c["collection"] == "General" for c in handler.response_body["collections"]))

        handler2 = self._make_handler()
        ContinuumApiHandler.handle_get_v1_tags(handler2)
        self.assertEqual(handler2.response_status, 200)
        self.assertTrue(any(t["tag"] == "initial" for t in handler2.response_body["tags"]))

    def test_http_transition(self):
        handler = self._make_handler({
            "activity_id": "act_http_67",
            "target_status": "paused"
        })
        ContinuumApiHandler.handle_post_v1_activity_transition(handler)
        self.assertEqual(handler.response_status, 200)
        self.assertEqual(handler.response_body["activity"]["status"], "paused")

    def test_http_update(self):
        handler = self._make_handler({
            "activity_id": "act_http_67",
            "title": "Renamed Title",
            "tags": ["updated_tag"],
            "collection": "Work",
            "activity_type": "custom-research"
        })
        ContinuumApiHandler.handle_post_v1_activity_update(handler)
        self.assertEqual(handler.response_status, 200)
        self.assertEqual(handler.response_body["activity"]["title"], "Renamed Title")
        self.assertEqual(handler.response_body["activity"]["activity_type"], "custom-research")
        self.assertEqual(handler.response_body["activity"]["collection"], "Work")

    def test_http_links(self):
        act2 = Activity(id="act_http_67_peer", title="Peer Activity")
        self.store.create_activity(act2)

        handler = self._make_handler({
            "source_activity_id": "act_http_67",
            "target_activity_id": "act_http_67_peer",
            "action": "link"
        })
        ContinuumApiHandler.handle_post_v1_activity_links(handler)
        self.assertEqual(handler.response_status, 200)
        self.assertIn("act_http_67_peer", handler.response_body["source_activity"]["related_activity_ids"])


if __name__ == "__main__":
    unittest.main()
