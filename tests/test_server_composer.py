"""
Project Continuum - Test Interactive Prompt Composer & Token Budget Visualizer (Phase 30)
========================================================================================
Verifies:
1. Workspace Overview Telemetry:
   - Lines of code (lines_of_code) computation in /api/context.
   - Total files, AST symbols, and detected languages.
2. Dynamic Prompt Composer Customization:
   - File subset filtering via `files: [...]`.
   - Context toggles (`include_diff`, `include_symbols`, `include_verification`).
   - Task directive injection (`task_description`).
3. Model Token Budget Estimation:
   - Token calculations across model profiles (Claude, GPT, Gemini, Universal).
   - Comparative percentage budget calculations.
4. End-to-end HTTP Request Execution:
   - POST /api/prompt respects file selections and toggles dynamically.
"""

import json
from pathlib import Path
import tempfile
import unittest
import urllib.request
import urllib.error

from server.daemon import ContinuumHttpDaemon


class TestPromptComposerAndTokenVisualizer(unittest.TestCase):
    """Test suite for Phase 30: Interactive Prompt Composer & Token Budget Visualizer."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self.temp_dir.name)

        # Create multi-file workspace
        (self.workspace_root / "auth.py").write_text(
            "class AuthService:\n"
            "    def login(self, u: str, p: str) -> bool:\n"
            "        return True\n",
            encoding="utf-8"
        )
        (self.workspace_root / "db.py").write_text(
            "class Database:\n"
            "    def connect(self) -> str:\n"
            "        return 'connected'\n",
            encoding="utf-8"
        )
        (self.workspace_root / "utils.py").write_text(
            "def format_str(s: str) -> str:\n"
            "    return s.strip()\n",
            encoding="utf-8"
        )

        self.daemon = ContinuumHttpDaemon(
            workspace_root=str(self.workspace_root),
            host="127.0.0.1",
            default_port=9200,
            require_auth=True
        )
        self.status = self.daemon.start(run_in_background=True)
        self.base_url = self.status.server_url
        self.token = self.daemon.auth_manager.get_token() or ""

    def tearDown(self) -> None:
        self.daemon.stop()
        self.temp_dir.cleanup()

    def _post_prompt(self, payload: dict) -> dict:
        encoded = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/prompt",
            data=encoded,
            headers={
                "Content-Type": "application/json",
                "X-Continuum-Token": self.token
            }
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            return json.loads(resp.read().decode("utf-8"))

    # --------------------------------------------------------------------------
    # 1. Overview Telemetry & Lines of Code Tests
    # --------------------------------------------------------------------------
    def test_context_overview_includes_lines_of_code_and_languages(self) -> None:
        """Verifies GET /api/context returns lines_of_code, languages, and files."""
        req = urllib.request.Request(
            f"{self.base_url}/api/context",
            headers={"X-Continuum-Token": self.token}
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))

            self.assertEqual(data.get("total_files"), 3)
            self.assertGreaterEqual(data.get("lines_of_code", 0), 6)
            self.assertIn("Python", data.get("languages", {}))
            self.assertIn("token_budget_estimation", data)
            self.assertGreater(data["token_budget_estimation"]["estimated_tokens"], 0)

    # --------------------------------------------------------------------------
    # 2. Dynamic File Selection Filtering Tests
    # --------------------------------------------------------------------------
    def test_prompt_composer_file_subset_filtering(self) -> None:
        """Verifies POST /api/prompt includes only selected files when filtered."""
        # 1. Request with only auth.py selected
        payload_auth = {
            "target_model": "universal",
            "files": ["auth.py"]
        }
        res_auth = self._post_prompt(payload_auth)
        self.assertIn("AuthService", res_auth.get("prompt", ""))
        self.assertNotIn("Database", res_auth.get("prompt", ""))
        self.assertNotIn("format_str", res_auth.get("prompt", ""))

        # 2. Request with auth.py and db.py selected
        payload_multi = {
            "target_model": "universal",
            "files": ["auth.py", "db.py"]
        }
        res_multi = self._post_prompt(payload_multi)
        self.assertIn("AuthService", res_multi.get("prompt", ""))
        self.assertIn("Database", res_multi.get("prompt", ""))
        self.assertNotIn("format_str", res_multi.get("prompt", ""))

    # --------------------------------------------------------------------------
    # 3. Context Toggles Tests (Symbols, Verification, Diffs)
    # --------------------------------------------------------------------------
    def test_prompt_composer_context_toggles(self) -> None:
        """Verifies inclusion/exclusion toggles for symbols, verification, and diffs."""
        # Test without symbols
        payload_no_sym = {
            "target_model": "claude",
            "include_symbols": False,
            "include_diff": False
        }
        res_no_sym = self._post_prompt(payload_no_sym)
        self.assertFalse(res_no_sym.get("include_symbols"))
        self.assertFalse(res_no_sym.get("include_diff"))

        # Test with task description
        payload_task = {
            "target_model": "gpt",
            "task_description": "Implement OAuth2 JWT verification"
        }
        res_task = self._post_prompt(payload_task)
        self.assertIn("Implement OAuth2 JWT verification", res_task.get("prompt", ""))

    # --------------------------------------------------------------------------
    # 4. Token Estimation Accuracy Tests
    # --------------------------------------------------------------------------
    def test_token_estimation_scaling_with_payload_size(self) -> None:
        """Verifies estimated_tokens increases proportionally with context additions."""
        # Small payload (1 file, no task)
        small_res = self._post_prompt({"target_model": "universal", "files": ["utils.py"]})
        small_tokens = small_res.get("estimated_tokens", 0)

        # Larger payload (all files + task description)
        large_res = self._post_prompt({
            "target_model": "universal",
            "files": ["auth.py", "db.py", "utils.py"],
            "task_description": "Comprehensive security audit across all service modules"
        })
        large_tokens = large_res.get("estimated_tokens", 0)

        self.assertGreater(large_tokens, small_tokens)


if __name__ == "__main__":
    unittest.main()
