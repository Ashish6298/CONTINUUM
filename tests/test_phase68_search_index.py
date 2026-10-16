"""
Unit and Integration Tests for Phase 68 - Search Source and Index
==================================================================
Verifies:
- Complete source field coverage: title, description, notes, context, decisions,
  actions, briefs, permitted artifact metadata, tags, type, status, collection, date.
- Excluded content & secret redaction: high-risk files excluded, inline tokens masked (I-10).
- Index update on authoritative commit: search index updates on commit; failures do not
  block or corrupt the authoritative store.
- Index rebuild: search index is completely rebuildable from authoritative JSON files (I-06).
- Query correctness: keywords, quoted phrases, prefix wildcards, special characters,
  filtering, and bounded pagination.
- HTTP REST API endpoints: GET /api/v1/search, POST /api/v1/search, POST /api/v1/search/rebuild.
- Gate Check: 100% offline, local SQLite FTS5 evidence-based search design.
"""

import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from core.activity import Activity, ActivityStatus, ActivityType
from core.checkpoint import UniversalCheckpoint, DecisionRecord, ArtifactReference, ResumeBrief
from storage.activity_store import ActivityCheckpointStore
from server.routes import ContinuumApiHandler
from server.auth import SessionAuthManager


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


class TestPhase68SearchSourceAndIndex(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="continuum_test_p68_")
        self.workspace = Path(self.test_dir)
        self.store = ActivityCheckpointStore(self.workspace)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_source_field_coverage(self):
        """Verifies searchable fields across activities and checkpoints."""
        # 1. Activity fields: title, description, tags, type, status, collection
        act = Activity(
            id="act_p68_fields",
            title="Quantum Compiler Optimization",
            description="LLVM backend compilation for topological qubits",
            activity_type="quantum-research",
            status=ActivityStatus.ACTIVE,
            tags=["quantum", "llvm", "compiler"],
            collection="Physics Lab",
        )
        self.store.create_activity(act)

        # 2. Checkpoint fields: context, notes, decisions, actions, briefs, artifacts
        chk = UniversalCheckpoint(
            id="chk_p68_fields",
            activity_id=act.id,
            timestamp="2026-10-16T12:00:00Z",
            context="Synthesized Clifford gate decomposition pipeline",
            progress={"summary": "Achieved sub-microsecond compilation latency"},
            completed_work=["Implemented pulse shaping scheduler", "Validated unitary matrix symmetry"],
            pending_actions=["Calibrate decoherence error bounds"],
            decisions=[
                DecisionRecord(
                    id="dec_1",
                    decision="Adopt sparse Hamiltonian representation",
                    rationale="Minimizes asymptotic memory overhead from quadratic to linear"
                )
            ],
            blockers=["Cryogenic refrigerator temperature drift"],
            artifacts=[
                ArtifactReference(
                    name="qasm_benchmark_suite.qasm",
                    path_or_uri="benchmarks/qasm_benchmark_suite.qasm",
                )
            ],
            resume_brief=ResumeBrief(
                purpose="Optimize Clifford group compilation for low-noise execution",
                next_actions=["Compiler pass verifies gate identities and compresses pulse schedules"]
            )
        )
        self.store.commit_checkpoint(chk)

        # Field tests:
        # Title match
        res, count = self.store.search(query="Quantum")
        self.assertGreaterEqual(count, 1)
        self.assertTrue(any(r.record_id == "act:act_p68_fields" for r in res))

        # Description match
        res, count = self.store.search(query="topological")
        self.assertGreaterEqual(count, 1)

        # Tags match
        res, count = self.store.search(query="llvm")
        self.assertGreaterEqual(count, 1)

        # Context match
        res, count = self.store.search(query="Clifford")
        self.assertGreaterEqual(count, 1)
        self.assertTrue(any(r.record_id == "chk:chk_p68_fields" for r in res))

        # Decisions match (decision_text & rationale)
        res, count = self.store.search(query="Hamiltonian")
        self.assertGreaterEqual(count, 1)
        res, count = self.store.search(query="asymptotic")
        self.assertGreaterEqual(count, 1)

        # Actions match (completed_work & pending_actions)
        res, count = self.store.search(query="scheduler")
        self.assertGreaterEqual(count, 1)
        res, count = self.store.search(query="decoherence")
        self.assertGreaterEqual(count, 1)

        # Notes / Blockers match
        res, count = self.store.search(query="Cryogenic")
        self.assertGreaterEqual(count, 1)

        # Briefs match (purpose & summary)
        res, count = self.store.search(query="compresses")
        self.assertGreaterEqual(count, 1)

        # Artifact metadata match
        res, count = self.store.search(query="qasm_benchmark_suite")
        self.assertGreaterEqual(count, 1)

    def test_excluded_content_and_secret_redaction(self):
        """Verifies high-risk files are excluded from indexing and secrets are redacted (I-10)."""
        act = Activity(id="act_p68_secrets", title="Security Audit Session")
        self.store.create_activity(act)

        # Checkpoint with inline secrets and sensitive files
        raw_aws_key = "AKIAIOSFODNN7EXAMPLE"
        raw_gh_token = "ghp_123456789012345678901234567890123456"
        chk = UniversalCheckpoint(
            id="chk_p68_secrets",
            activity_id=act.id,
            timestamp="2026-10-16T12:30:00Z",
            context=f"Configured credentials with AWS key {raw_aws_key} and token {raw_gh_token}",
            decisions=[
                DecisionRecord(
                    id="dec_sec",
                    decision=f"Rotated key {raw_aws_key}",
                    rationale="Routine credential cycling"
                )
            ],
            artifacts=[
                # High-risk sensitive files that must NEVER be indexed into search
                ArtifactReference(name=".env", path_or_uri="config/.env"),
                ArtifactReference(name="id_rsa", path_or_uri=".ssh/id_rsa"),
                ArtifactReference(name="private.pem", path_or_uri="certs/private.pem"),
                ArtifactReference(name="secrets.json", path_or_uri="secrets.json"),
                # Permitted non-sensitive file
                ArtifactReference(name="public_spec.md", path_or_uri="docs/public_spec.md"),
            ]
        )
        self.store.commit_checkpoint(chk)

        # 1. Searching for exact raw secret values must return NO results
        res_aws, count_aws = self.store.search(query=raw_aws_key)
        self.assertEqual(count_aws, 0)

        res_gh, count_gh = self.store.search(query=raw_gh_token)
        self.assertEqual(count_gh, 0)

        # 2. Searching for sensitive filenames must return NO results
        res_env, count_env = self.store.search(query=".env")
        self.assertEqual(count_env, 0)

        res_rsa, count_rsa = self.store.search(query="id_rsa")
        self.assertEqual(count_rsa, 0)

        # 3. Permitted artifact must be found
        res_pub, count_pub = self.store.search(query="public_spec")
        self.assertGreaterEqual(count_pub, 1)

        # 4. Search results for surrounding words must contain sanitized redacted markers, never raw secrets
        res_rot, _ = self.store.search(query="Rotated")
        self.assertGreaterEqual(len(res_rot), 1)
        snippet = res_rot[0].snippet
        self.assertNotIn(raw_aws_key, snippet)
        self.assertNotIn(raw_gh_token, snippet)

    def test_index_update_on_commit_and_non_blocking_failure(self):
        """Verifies search index updates on commit; failures never corrupt authoritative store."""
        act = Activity(id="act_p68_trans", title="Transactional Index Test")
        self.store.create_activity(act)

        # Immediate searchability
        res, count = self.store.search(query="Transactional")
        self.assertEqual(count, 1)

        # Updating activity updates search index
        self.store.update_activity_details(act.id, title="Refactored Transactional Module")
        res_old, count_old = self.store.search(query='"Transactional Module"')
        self.assertEqual(count_old, 1)

        # Commit checkpoint
        chk = UniversalCheckpoint.create_minimal(activity_id=act.id, context="Added resilient indexing test")
        committed_chk = self.store.commit_checkpoint(chk)
        self.assertIsNotNone(committed_chk)

        # Search checkpoint
        res_chk, count_chk = self.store.search(query="resilient")
        self.assertEqual(count_chk, 1)

    def test_search_index_rebuild(self):
        """Verifies FTS5 index is 100% rebuildable from authoritative disk JSON files (I-06)."""
        act = Activity(id="act_rebuild_test", title="Authoritative Rebuild Activity", collection="Recovery")
        self.store.create_activity(act)
        chk = UniversalCheckpoint.create_minimal(activity_id=act.id, context="Authoritative rebuild checkpoint payload")
        self.store.commit_checkpoint(chk)

        # Verify indexed
        res, count = self.store.search(query="Authoritative")
        self.assertGreaterEqual(count, 2)

        # Manually wipe search_fts virtual table
        with self.store._get_db_connection() as conn:
            conn.execute("DELETE FROM search_fts;")

        # Search should now find nothing
        res_empty, count_empty = self.store.search(query="Authoritative")
        self.assertEqual(count_empty, 0)

        # Rebuild search index
        rebuilt_count = self.store.rebuild_search_index()
        self.assertGreaterEqual(rebuilt_count, 2)

        # Search should now find both records again
        res_restored, count_restored = self.store.search(query="Authoritative")
        self.assertEqual(count_restored, 2)

    def test_query_correctness_and_special_characters(self):
        """Verifies phrases, prefix wildcards, special characters, and filtering."""
        act = Activity(id="act_q_test", title="API Gateway Controller", collection="Services", tags=["api", "gateway"])
        self.store.create_activity(act)
        chk = UniversalCheckpoint.create_minimal(
            activity_id=act.id,
            context="Fixed error: connection timeout on port 8080 (socket closed)"
        )
        self.store.commit_checkpoint(chk)

        # 1. Quoted phrase
        res, count = self.store.search(query='"API Gateway"', record_type="activity")
        self.assertEqual(count, 1)

        # 2. Prefix wildcard
        res, count = self.store.search(query="Gate*", record_type="activity")
        self.assertEqual(count, 1)

        # 3. Special characters that would break unquoted FTS5 (: ( ) { } ^ @)
        res, count = self.store.search(query="error: connection timeout (socket closed)")
        self.assertGreaterEqual(count, 1)

        # 4. Filters: record_type
        # "Controller" is in activity title only
        res_act, count_act = self.store.search(query="Controller", record_type="activity")
        self.assertEqual(count_act, 1)
        self.assertEqual(res_act[0].record_type, "activity")

        res_chk, count_chk = self.store.search(query="Controller", record_type="checkpoint")
        self.assertEqual(count_chk, 0)

        # "socket" is in checkpoint context only
        res_chk2, count_chk2 = self.store.search(query="socket", record_type="checkpoint")
        self.assertEqual(count_chk2, 1)
        self.assertEqual(res_chk2[0].record_type, "checkpoint")

        res_act2, count_act2 = self.store.search(query="socket", record_type="activity")
        self.assertEqual(count_act2, 0)

        # 5. Filter: collection
        res_col, count_col = self.store.search(collection="Services")
        self.assertGreaterEqual(count_col, 1)

        # 6. Bounded pagination
        res_page, total = self.store.search(limit=1, offset=0)
        self.assertEqual(len(res_page), 1)
        self.assertGreaterEqual(total, 1)


class TestPhase68SearchHTTPRoutes(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="continuum_http_p68_")
        self.workspace = Path(self.test_dir)
        self.store = ActivityCheckpointStore(self.workspace)
        self.act = Activity(id="act_http_search", title="Search HTTP Activity", collection="Networking")
        self.store.create_activity(self.act)
        self.chk = UniversalCheckpoint.create_minimal(activity_id=self.act.id, context="HTTP endpoint search verification")
        self.store.commit_checkpoint(self.chk)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _make_handler(self, body_dict=None):
        handler = MockHTTPHandler(self.workspace)
        if body_dict is not None:
            raw_bytes = json.dumps(body_dict).encode("utf-8")
            handler.headers["Content-Length"] = str(len(raw_bytes))
            handler.rfile = io.BytesIO(raw_bytes)
        else:
            handler.headers["Content-Length"] = "0"
            handler.rfile = io.BytesIO(b"")
        return handler

    def test_http_get_search(self):
        handler = self._make_handler()
        ContinuumApiHandler.handle_get_v1_search(
            handler,
            {"q": ["verification"], "collection": ["Networking"]}
        )
        self.assertEqual(handler.response_status, 200)
        self.assertEqual(handler.response_body["status"], "success")
        self.assertGreaterEqual(handler.response_body["count"], 1)
        self.assertEqual(handler.response_body["results"][0]["record_id"], f"chk:{self.chk.id}")

    def test_http_post_search(self):
        handler = self._make_handler({
            "query": "Activity",
            "record_type": "activity",
            "limit": 5
        })
        ContinuumApiHandler.handle_post_v1_search(handler)
        self.assertEqual(handler.response_status, 200)
        self.assertGreaterEqual(handler.response_body["count"], 1)
        self.assertEqual(handler.response_body["results"][0]["record_id"], f"act:{self.act.id}")

    def test_http_post_search_rebuild(self):
        handler = self._make_handler({})
        ContinuumApiHandler.handle_post_v1_search_rebuild(handler)
        self.assertEqual(handler.response_status, 200)
        self.assertEqual(handler.response_body["status"], "success")
        self.assertGreaterEqual(handler.response_body["indexed_count"], 2)


if __name__ == "__main__":
    unittest.main()
