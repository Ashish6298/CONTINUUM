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
        self.assertIn("@version      1.2.3", content)
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
        """Verifies Phase 39: ContextCompressor synthesizes ground-truth code, token budgeting, and multi-model tailored formatting."""
        content = self.userjs_path.read_text(encoding="utf-8")
        self.assertIn("class ContextCompressor", content)
        self.assertIn("_formatClaudeXML", content)
        self.assertIn("_formatGeminiHierarchy", content)
        self.assertIn("_formatDeepSeekCompact", content)
        self.assertIn("_formatMarkdownChecklist", content)
        self.assertIn("deduplicateCodeBlocks", content)
        self.assertIn("capTokenBudget", content)
        self.assertIn("<project_continuation_context>", content)
        self.assertIn("<verified_code_artifacts>", content)
        self.assertIn("<immediate_task>", content)
        self.assertIn("[1.0] PROJECT INTENT & SPECIFICATION", content)
        self.assertIn("[2.0] VERIFIED CODE REPOSITORY (GROUND TRUTH)", content)
        self.assertIn("[3.0] RECENT CONVERSATION STATE", content)
        self.assertIn("[4.0] NEXT IMMEDIATE EXECUTION TARGET", content)
        self.assertIn("[CONTINUUM HANDOFF: ", content)
        self.assertIn("--- CODE ARTIFACTS ---", content)
        self.assertIn("--- YOUR TASK ---", content)

    def test_cross_tab_relay_and_dom_injector(self):
        """Verifies Phase 40: CrossTabHandoff TTL expiry, routing, and ContinuumDOMInjector synthetic input dispatch engine."""
        content = self.userjs_path.read_text(encoding="utf-8")
        self.assertIn("class CrossTabHandoff", content)
        self.assertIn("class ContinuumDOMInjector", content)
        self.assertIn("findTargetInput(platform)", content)
        self.assertIn("dispatchInputEvents(el)", content)
        self.assertIn("inject(platform, text, mode", content)
        self.assertIn("InputEvent('beforeinput'", content)
        self.assertIn("Event('input'", content)
        self.assertIn("Event('change'", content)
        self.assertIn("KeyboardEvent('keydown'", content)
        self.assertIn("KeyboardEvent('keyup'", content)
        self.assertIn("90000", content)  # 90s TTL
        self.assertIn("https://claude.ai/new", content)
        self.assertIn("https://gemini.google.com/app", content)
        self.assertIn("https://chatgpt.com/", content)
        self.assertIn("https://chat.deepseek.com/", content)
        self.assertIn("ProseMirror", content)
        self.assertIn("GM_setClipboard", content)
        self.assertIn("navigator.clipboard", content)
        self.assertIn("document.execCommand('copy')", content)

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

    def test_native_manifest_v3_extension_packaging(self):
        """Verifies Phase 41: browser/extension/ directory contains valid Manifest V3 packaging."""
        import json
        ext_dir = Path(__file__).parent.parent / "browser" / "extension"
        manifest_path = ext_dir / "manifest.json"
        bg_path = ext_dir / "background.js"
        content_script_path = ext_dir / "content_script.js"
        icons_dir = ext_dir / "icons"

        self.assertTrue(manifest_path.is_file(), "manifest.json must exist")
        self.assertTrue(bg_path.is_file(), "background.js must exist")
        self.assertTrue(content_script_path.is_file(), "content_script.js must exist")
        self.assertTrue(icons_dir.is_dir(), "icons directory must exist")
        self.assertTrue((icons_dir / "icon16.png").is_file())
        self.assertTrue((icons_dir / "icon48.png").is_file())
        self.assertTrue((icons_dir / "icon128.png").is_file())

        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest_data.get("manifest_version"), 3)
        self.assertEqual(manifest_data.get("version"), "1.2.0")
        self.assertIn("storage", manifest_data.get("permissions", []))
        self.assertIn("https://chatgpt.com/*", manifest_data.get("host_permissions", []))
        self.assertIn("https://claude.ai/*", manifest_data.get("host_permissions", []))
        self.assertIn("https://gemini.google.com/*", manifest_data.get("host_permissions", []))
        self.assertIn("https://chat.deepseek.com/*", manifest_data.get("host_permissions", []))

    def test_browser_launcher_discovery_and_cli_subcommand(self):
        """Verifies Phase 42: BrowserLauncher discovers browser binaries and builds launch command."""
        from core.launcher import BrowserLauncher, TARGET_URLS
        from cli.main import build_parser, main
        import io
        from unittest.mock import patch

        launcher = BrowserLauncher()
        self.assertTrue(launcher.extension_path.is_dir())
        self.assertEqual(TARGET_URLS["claude"], "https://claude.ai/new")
        self.assertEqual(TARGET_URLS["gemini"], "https://gemini.google.com/app")
        self.assertEqual(TARGET_URLS["deepseek"], "https://chat.deepseek.com/")

        # Test dry-run execution
        success, msg = launcher.launch(target_model="claude", dry_run=True)
        self.assertTrue(success)
        self.assertIn("[DRY-RUN]", msg)
        self.assertIn("https://claude.ai/new", msg)

        # Test CLI parser support
        parser = build_parser()
        args = parser.parse_args(["launch", "--target", "gemini", "--dry-run"])
        self.assertEqual(args.command, "launch")
        self.assertEqual(args.target, "gemini")
        self.assertTrue(args.dry_run)

        # Test main CLI execution
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            exit_code = main(["launch", "--target", "deepseek", "--dry-run"])
            self.assertEqual(exit_code, 0)
            self.assertIn("[OK] [DRY-RUN]", fake_out.getvalue())
            self.assertIn("https://chat.deepseek.com/", fake_out.getvalue())

    def test_bookmarklet_generator_and_cli_subcommand(self):
        """Verifies Phase 43: BookmarkletGenerator produces valid javascript: URI, minification, and HTML installer."""
        from cli.bookmarklet import BookmarkletGenerator
        from cli.main import build_parser, main
        import io
        from unittest.mock import patch

        gen = BookmarkletGenerator()
        raw_js = gen.get_javascript_code()
        self.assertNotIn("// ==UserScript==", raw_js)
        self.assertIn("ChatConversationExtractor", raw_js)

        minified = gen.minify(raw_js)
        self.assertNotIn("\n\n", minified)

        uri = gen.generate_bookmarklet_uri()
        self.assertTrue(uri.startswith("javascript:"))
        self.assertIn("Continuum", uri)

        # Test installer HTML generation
        html = gen.generate_installer_html()
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Continuum Bookmarklet", html)
        self.assertIn("Drag me to Bookmarks Bar", html)

        # Test CLI invocation --raw
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            exit_code = main(["bookmarklet", "--raw"])
            self.assertEqual(exit_code, 0)
            self.assertTrue(fake_out.getvalue().strip().startswith("javascript:"))

        # Test CLI invocation --html
        with tempfile.TemporaryDirectory() as tmpdir:
            out_html = Path(tmpdir) / "test_installer.html"
            exit_code = main(["bookmarklet", "--html", str(out_html)])
            self.assertEqual(exit_code, 0)
            self.assertTrue(out_html.is_file())
            self.assertIn("Continuum Bookmarklet", out_html.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
