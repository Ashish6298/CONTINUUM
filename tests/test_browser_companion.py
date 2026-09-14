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
        self.assertTrue(self.userjs_path.is_file(), "continuum.user.js must exist")
        content = self.userjs_path.read_text(encoding="utf-8")
        self.assertIn("// ==UserScript==", content)
        self.assertIn("// ==/UserScript==", content)
        self.assertIn("@name         Continuum - Local AI Work Continuity", content)
        self.assertIn("@version      1.2.0", content)
        expected_matches = [
            "https://chatgpt.com/*",
            "https://claude.ai/*",
            "https://aistudio.google.com/*",
            "https://gemini.google.com/*",
            "https://chat.deepseek.com/*"
        ]
        for m in expected_matches:
            self.assertIn(f"// @match        {m}", content)

        expected_grants = [
            "GM_xmlhttpRequest",
            "GM_setValue",
            "GM_getValue",
            "GM_addStyle"
        ]
        for g in expected_grants:
            self.assertIn(f"// @grant        {g}", content)

        self.assertIn("// @connect      localhost", content)
        self.assertIn("// @connect      127.0.0.1", content)

    def test_userscript_shadow_dom_and_floating_ui_components(self):
        """Verifies Phase 34: Encapsulated Shadow DOM, hotkey handler, and quick menu options."""
        content = self.userjs_path.read_text(encoding="utf-8")
        self.assertIn("attachShadow({ mode: 'open' })", content)
        self.assertIn("continuum-companion-root", content)
        self.assertIn("continuum-badge", content)
        self.assertIn("continuum-modal", content)
        self.assertIn("status-dot", content)
        self.assertIn("actInjectFull", content)
        self.assertIn("actInjectDiff", content)
        self.assertIn("actInjectSymbols", content)
        self.assertIn("actOpenDashboard", content)
        self.assertIn("altKey", content)
        self.assertIn("Alt+C", content)

    def test_userscript_http_delivery_and_token_injection(self):
        token = self.daemon.auth_manager.get_token()
        self.assertTrue(bool(token))
        url = f"{self.base_url}/continuum.user.js"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            content_type = resp.headers.get("Content-Type", "")
            self.assertIn("application/javascript", content_type)
            body = resp.read().decode("utf-8")
            self.assertIn("// ==UserScript==", body)
            self.assertIn(f"defaultToken: '{token}'", body)

    def test_dom_injectors_and_synthetic_event_adapters(self):
        """Verifies Phase 35: DOM selectors for ChatGPT, Claude, AI Studio, DeepSeek, synthetic events, and insertion modes."""
        content = self.userjs_path.read_text(encoding="utf-8")
        self.assertIn("class ContinuumDOMInjector", content)
        self.assertIn("findTargetInput(platform)", content)
        self.assertIn("dispatchInputEvents(element)", content)
        self.assertIn("inject(platform, text, mode", content)
        
        # Selectors
        self.assertIn("#prompt-textarea", content)
        self.assertIn(".ProseMirror[contenteditable=\"true\"]", content)
        self.assertIn("textarea.chat-input", content)
        self.assertIn("textarea[placeholder*=\"Ask\"]", content)
        
        # Synthetic event triggers
        self.assertIn("InputEvent('beforeinput'", content)
        self.assertIn("Event('input'", content)
        self.assertIn("Event('change'", content)
        self.assertIn("KeyboardEvent('keydown'", content)
        
        # Insertion modes
        self.assertIn("mode = 'replace'", content)
        self.assertIn("mode === 'prepend'", content)
        self.assertIn("mode === 'append'", content)
        self.assertIn("selInsertionMode", content)

    def test_dashboard_contains_install_companion_button(self):
        index_html_path = Path(__file__).parent.parent / "server" / "static" / "index.html"
        html_content = index_html_path.read_text(encoding="utf-8")
        self.assertIn('id="btnInstallCompanion"', html_content)
        self.assertIn('href="/continuum.user.js"', html_content)

if __name__ == "__main__":
    unittest.main()

