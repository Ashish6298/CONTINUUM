"""
Project Continuum - Test REST API Endpoints (Phase 26)
======================================================
Verifies:
1. GET /api/status - Returns status, version, git info, workspace root.
2. GET /api/context - Returns canonical analysis, files, symbols, token budgets.
3. GET /api/symbols - Returns AST symbols with file and type filtering.
4. GET /api/diff - Returns staged and unstaged Git diffs.
5. POST /api/prompt - Generates model-tailored prompts (Claude, GPT, Gemini, Universal).
6. Error handling - 404 on missing routes, 400 on invalid JSON payloads.
"""

import json
from pathlib import Path
import tempfile
import time
from typing import Any, Dict, List, Optional
import unittest
import urllib.request
import urllib.error

from server.daemon import ContinuumHttpDaemon
from server.routes import ContinuumApiHandler


class TestRestApiEndpoints(unittest.TestCase):
    """Test suite for Phase 26: REST API Endpoints & Live Workspace Handlers."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self.temp_dir.name).resolve()

        # Create sample workspace files
        self.app_file = self.workspace_root / "app.py"
        self.app_file.write_text(
            "class UserService:\n"
            "    def authenticate(self, username: str) -> bool:\n"
            "        return True\n\n"
            "def main():\n"
            "    print('App running')\n",
            encoding="utf-8"
        )

        self.daemon = ContinuumHttpDaemon(
            workspace_root=str(self.workspace_root),
            host="127.0.0.1",
            default_port=8960
        )
        self.status = self.daemon.start(run_in_background=True)
        self.base_url = self.status.server_url

    def tearDown(self) -> None:
        self.daemon.stop()
        self.temp_dir.cleanup()

    def _get_json(self, endpoint: str) -> Dict:
        headers = {"X-Continuum-Token": self.daemon.auth_manager.get_token() or ""}
        req = urllib.request.Request(f"{self.base_url}{endpoint}", headers=headers)
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            return json.loads(resp.read().decode("utf-8"))

    def _post_json(self, endpoint: str, data: Dict) -> Dict:
        encoded = json.dumps(data).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Continuum-Token": self.daemon.auth_manager.get_token() or ""
        }
        req = urllib.request.Request(
            f"{self.base_url}{endpoint}",
            data=encoded,
            headers=headers
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            return json.loads(resp.read().decode("utf-8"))

    def test_get_status_endpoint(self) -> None:
        """Test GET /api/status returns valid health and environment metadata."""
        data = self._get_json("/api/status")
        self.assertEqual(data.get("status"), "online")
        self.assertEqual(data.get("version"), "1.2.0-dev")
        self.assertEqual(Path(data.get("workspace_root", "")).resolve(), self.workspace_root)
        self.assertIn("server_started_at", data)
        self.assertIn("timestamp", data)

    def test_get_context_endpoint(self) -> None:
        """Test GET /api/context executes analysis and computes token budgets."""
        data = self._get_json("/api/context")
        self.assertEqual(Path(data.get("workspace_root", "")).resolve(), self.workspace_root)
        self.assertIn("token_budget_estimation", data)
        self.assertGreater(data["token_budget_estimation"]["estimated_tokens"], 0)
        self.assertIn("languages", data)
        self.assertIn("Python", data["languages"])

    def test_get_symbols_endpoint_and_filtering(self) -> None:
        """Test GET /api/symbols extracts symbols and supports filtering."""
        data = self._get_json("/api/symbols")
        self.assertGreaterEqual(data.get("total_symbols_found", 0), 2)
        symbols = data.get("symbols", [])
        names = [s.get("name") for s in symbols]
        self.assertIn("UserService", names)
        self.assertTrue("UserService.authenticate" in names or "authenticate" in names)
        self.assertIn("main", names)

        # Test filtering by file
        filtered = self._get_json("/api/symbols?file=app.py")
        self.assertEqual(len(filtered.get("symbols", [])), len(symbols))

    def test_get_diff_endpoint(self) -> None:
        """Test GET /api/diff returns structured diff response."""
        data = self._get_json("/api/diff")
        self.assertIn("is_git_repository", data)
        self.assertIn("staged_diff", data)
        self.assertIn("unstaged_diff", data)

    def test_post_prompt_endpoint_claude_and_gpt(self) -> None:
        """Test POST /api/prompt formats tailored handoff prompts."""
        # Test Claude Format
        claude_req = {
            "target_model": "claude",
            "task_description": "Implement OAuth2 login handler",
            "include_diff": True
        }
        res_claude = self._post_json("/api/prompt", claude_req)
        self.assertEqual(res_claude.get("target_model"), "claude")
        self.assertIn("Implement OAuth2 login handler", res_claude.get("prompt", ""))
        self.assertGreater(res_claude.get("estimated_tokens", 0), 0)

        # Test GPT Format
        gpt_req = {
            "target_model": "gpt",
            "task_description": "Write unit tests for UserService"
        }
        res_gpt = self._post_json("/api/prompt", gpt_req)
        self.assertEqual(res_gpt.get("target_model"), "gpt")
        self.assertIn("Write unit tests for UserService", res_gpt.get("prompt", ""))

    def test_error_handling_404_and_400(self) -> None:
        """Test 404 for unknown endpoints and 400 for bad payloads."""
        token = self.daemon.auth_manager.get_token() or ""
        # Test 404
        req_404 = urllib.request.Request(
            f"{self.base_url}/api/non_existent_route",
            headers={"X-Continuum-Token": token}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_404)
        self.assertEqual(ctx.exception.code, 404)

        # Test 400 bad JSON
        req_400 = urllib.request.Request(
            f"{self.base_url}/api/prompt",
            data=b"INVALID_JSON{",
            headers={
                "Content-Type": "application/json",
                "X-Continuum-Token": token
            }
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_400)
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
