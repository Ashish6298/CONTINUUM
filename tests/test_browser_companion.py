"""
Project Continuum - Test Suite for Browser Companion & Chat-to-Chat Handoff
=============================================================================
Phase 38: Multi-Platform Chat DOM Conversation & Code Extractor
Phase 39: Context Compression & Ground-Truth Prompt Synthesis
Phase 40: Cross-Tab Relay & Synthetic DOM Input Injection
"""

from pathlib import Path
import tempfile
import unittest
import urllib.request
from server.daemon import ContinuumHttpDaemon


class TestBrowserCompanionDistribution(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self.temp_dir.name)
        self.userjs_path = Path(__file__).parent.parent / "browser" / "continuum.user.js"

        self.daemon = ContinuumHttpDaemon(
            workspace_root=str(self.workspace_root),
            host="127.0.0.1",
            default_port=9150,
            require_auth=True
        )
        self.status = self.daemon.start(run_in_background=True)
        self.base_url = self.status.server_url

    def tearDown(self):
        self.daemon.stop()
        self.temp_dir.cleanup()

    def test_userscript_metadata_headers_and_matches(self):
        """Verifies Phase 38: Tampermonkey metadata headers, platform URL matches, and permissions."""
        self.assertTrue(self.userjs_path.is_file(), "continuum.user.js must exist")
        content = self.userjs_path.read_text(encoding="utf-8")
        self.assertIn("// ==UserScript==", content)
        self.assertIn("// ==/UserScript==", content)
        self.assertIn("@name         Continuum - AI Chat Handoff", content)
        self.assertIn("@version      1.2.2", content)
        expected_matches = [
            "https://chatgpt.com/*",
            "https://claude.ai/*",
            "https://aistudio.google.com/*",
            "https://gemini.google.com/*",
            "https://chat.deepseek.com/*"
        ]
        for m in expected_matches:
            self.assertIn(f"// @match        {m}", content)

        self.assertIn("// @grant        GM_setClipboard", content)

    def test_userscript_shadow_dom_and_floating_ui_components(self):
        """Verifies Phase 38 UI: Encapsulated Shadow DOM, hotkey handler, badge, and handoff action buttons."""
        content = self.userjs_path.read_text(encoding="utf-8")
        self.assertIn("attachShadow({ mode: 'open' })", content)
        self.assertIn("continuum-companion-root", content)
        self.assertIn('class="badge"', content)
        self.assertIn('class="modal"', content)
        self.assertIn('id="btnCopy"', content)
        self.assertIn('id="sgrid"', content)
        self.assertIn("altKey", content)
        self.assertIn("Alt+C", content)

    def test_chat_conversation_extractor_multi_platform_support(self):
        """Verifies Phase 38: ChatConversationExtractor contains DOM selectors for all 4 major platforms."""
        content = self.userjs_path.read_text(encoding="utf-8")
        self.assertIn("class ChatConversationExtractor", content)
        self.assertIn("_extractChatGPT()", content)
        self.assertIn("_extractClaude()", content)
        self.assertIn("_extractGemini()", content)
        self.assertIn("_extractDeepSeek()", content)
        self.assertIn("_extractGeneric()", content)

        # Platform specific selectors
        self.assertIn("[data-message-author-role]", content)
        self.assertIn(".human-turn", content)
        self.assertIn("user-query", content)
        self.assertIn(".chat-message", content)
        self.assertIn("pre code", content)

    def test_context_compressor_and_prompt_synthesis(self):
        """Verifies Phase 39: ContextCompressor synthesizes ground-truth code and next tasks."""
        content = self.userjs_path.read_text(encoding="utf-8")
        self.assertIn("class ContextCompressor", content)
        self.assertIn("CONTINUUM HANDOFF", content)
        self.assertIn("Ground truth = the code blocks below", content)
        self.assertIn("All Code Produced So Far", content)
        self.assertIn("YOUR IMMEDIATE TASK", content)

    def test_cross_tab_relay_and_dom_injector(self):
        """Verifies Phase 40: CrossTabHandoff and ContinuumDOMInjector with synthetic event dispatching."""
        content = self.userjs_path.read_text(encoding="utf-8")
        self.assertIn("class CrossTabHandoff", content)
        self.assertIn("class ContinuumDOMInjector", content)
        self.assertIn("findTargetInput(platform)", content)
        self.assertIn("dispatchInputEvents(el)", content)
        self.assertIn("inject(platform, text, mode", content)
        self.assertIn("InputEvent('beforeinput'", content)
        self.assertIn("Event('input'", content)
        self.assertIn("Event('change'", content)

    def test_userscript_http_delivery(self):
        """Verifies Phase 38: Local daemon properly serves continuum.user.js over HTTP."""
        url = f"{self.base_url}/continuum.user.js"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            content_type = resp.headers.get("Content-Type", "")
            self.assertIn("application/javascript", content_type)
            body = resp.read().decode("utf-8")
            self.assertIn("// ==UserScript==", body)
            self.assertIn("class ChatConversationExtractor", body)

    def test_dashboard_contains_install_companion_button(self):
        index_html_path = Path(__file__).parent.parent / "server" / "static" / "index.html"
        html_content = index_html_path.read_text(encoding="utf-8")
        self.assertIn('id="btnInstallCompanion"', html_content)
        self.assertIn('href="/continuum.user.js"', html_content)


if __name__ == "__main__":
    unittest.main()
