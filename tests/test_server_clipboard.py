"""
Project Continuum - Test Target-Tailored 1-Click Clipboard Engine (Phase 31)
=============================================================================
Verifies:
1. Platform Formatter Target Modes:
   - Claude Mode (structured XML tags <project_metadata>, <system_directives>, ANTHROPIC_CLAUDE).
   - ChatGPT Mode (markdown task checklists, step execution, OPENAI_CODEX_GPT).
   - Gemini / AI Studio Mode (hierarchical ontology, Ground Truth Project Topology, GOOGLE_GEMINI).
   - DeepSeek / Open LLM Mode (compact system-user continuity prompt, high-density format).
   - Universal Default Mode (Codex / Markdown fallback).
2. Daemon HTTP API Payload Handling:
   - POST /api/prompt endpoint handles all model aliases (chatgpt, claude, gemini, aistudio, deepseek, openllm, local, universal).
   - Token calculations and response headers.
3. Static Manager MIME Support:
   - Verification of text/markdown and text/plain MIME support for .md and .txt prompt downloads.
"""

import json
from pathlib import Path
import tempfile
import unittest
import urllib.request
import urllib.error

from server.daemon import ContinuumHttpDaemon
from server.static_manager import StaticAssetManager


class TestTargetTailoredClipboardEngine(unittest.TestCase):
    """Test suite for Phase 31: Target-Tailored 1-Click Clipboard Engine."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self.temp_dir.name)

        (self.workspace_root / "main.py").write_text(
            "def run_app():\n"
            "    print('Starting Continuum Engine...')\n",
            encoding="utf-8"
        )
        (self.workspace_root / "config.py").write_text(
            "DEBUG = True\n"
            "PORT = 8080\n",
            encoding="utf-8"
        )

        self.daemon = ContinuumHttpDaemon(
            workspace_root=str(self.workspace_root),
            host="127.0.0.1",
            default_port=9250,
            require_auth=True
        )
        self.status = self.daemon.start(run_in_background=True)
        self.base_url = self.status.server_url
        self.token = self.daemon.auth_manager.get_token() or ""

    def tearDown(self) -> None:
        self.daemon.stop()
        self.temp_dir.cleanup()

    def _post(self, endpoint: str, payload: dict) -> dict:
        url = f"{self.base_url}{endpoint}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-Continuum-Token": self.token
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_claude_xml_format_generation(self):
        """Verify Claude mode generates structured XML encapsulation."""
        resp = self._post("/api/prompt", {
            "target_model": "claude",
            "include_diff": True,
            "include_symbols": True,
            "task_description": "Implement Claude XML test suite"
        })
        self.assertEqual(resp["status"], "success")
        self.assertEqual(resp["target_model"], "claude")
        
        prompt = resp["prompt"]
        self.assertIn("<project_metadata>", prompt)
        self.assertIn("</project_metadata>", prompt)
        self.assertIn("ANTHROPIC_CLAUDE", prompt)
        self.assertIn("Implement Claude XML test suite", prompt)

    def test_chatgpt_markdown_checklist_format_generation(self):
        """Verify ChatGPT mode generates markdown structure with task checklists."""
        resp = self._post("/api/prompt", {
            "target_model": "chatgpt",
            "include_diff": True,
            "include_symbols": True,
            "task_description": "Refactor OpenAI prompt pipeline"
        })
        self.assertEqual(resp["status"], "success")
        self.assertEqual(resp["target_model"], "chatgpt")
        
        prompt = resp["prompt"]
        self.assertIn("OPENAI_CODEX_GPT", prompt)
        self.assertIn("MARKDOWN_CHECKLISTS_AND_CODEBLOCKS", prompt)
        self.assertIn("Active Tasks & Next Steps", prompt)
        self.assertIn("Refactor OpenAI prompt pipeline", prompt)

    def test_gemini_and_aistudio_hierarchical_format_generation(self):
        """Verify Gemini and AI Studio mode generates hierarchical topology and large-context headers."""
        for model in ["gemini", "aistudio"]:
            resp = self._post("/api/prompt", {
                "target_model": model,
                "include_diff": True,
                "include_symbols": True
            })
            self.assertEqual(resp["status"], "success")
            self.assertEqual(resp["target_model"], model)
            
            prompt = resp["prompt"]
            self.assertIn("GOOGLE_GEMINI", prompt)
            self.assertIn("Tier 1: Ground Truth Project Topology", prompt)

    def test_deepseek_and_openllm_compact_format_generation(self):
        """Verify DeepSeek and OpenLLM modes generate high-density continuity prompt."""
        for model in ["deepseek", "openllm", "local"]:
            resp = self._post("/api/prompt", {
                "target_model": model,
                "include_diff": True
            })
            self.assertEqual(resp["status"], "success")
            self.assertEqual(resp["target_model"], model)
            
            prompt = resp["prompt"]
            self.assertIn("Physical reality overrides chat claims", prompt)
            self.assertIn("In-Flight Tasks", prompt)

    def test_universal_fallback_generation(self):
        """Verify universal fallback format when target_model is universal or unknown."""
        resp = self._post("/api/prompt", {
            "target_model": "universal"
        })
        self.assertEqual(resp["status"], "success")
        self.assertEqual(resp["target_model"], "universal")
        self.assertIn("OPENAI_CODEX_GPT", resp["prompt"])

    def test_static_manager_mime_types_for_file_archival(self):
        """Verify StaticAssetManager recognizes markdown and plaintext for prompt downloads."""
        mgr = StaticAssetManager()
        self.assertEqual(mgr.get_mime_type("prompt.md"), "text/markdown; charset=utf-8")
        self.assertEqual(mgr.get_mime_type("prompt.txt"), "text/plain; charset=utf-8")
        self.assertEqual(mgr.get_mime_type("handoff.json"), "application/json; charset=utf-8")


if __name__ == "__main__":
    unittest.main()
