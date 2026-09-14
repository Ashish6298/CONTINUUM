"""
Project Continuum - Test Embedded Dashboard & Static Asset Serving (Phase 29)
=============================================================================
Verifies:
1. Static asset manager resolution from source / package resources:
   - index.html, dashboard.css, dashboard.js.
2. Correct MIME type headers:
   - text/html for HTML.
   - text/css for CSS.
   - application/javascript for JS.
3. Path security and directory traversal guard:
   - Rejects attempts to traverse outside static/ with 404/None.
4. HTTP daemon end-to-end static serving:
   - Root (/) returns index.html with 200 OK.
   - /dashboard.css returns stylesheet with 200 OK.
   - /dashboard.js returns JavaScript client with 200 OK.
"""

from pathlib import Path
import tempfile
import unittest
import urllib.request
import urllib.error

from server.daemon import ContinuumHttpDaemon
from server.static_manager import StaticAssetManager


class TestEmbeddedDashboardStaticServing(unittest.TestCase):
    """Test suite for Phase 29: Embedded Dashboard Architecture & Asset Serving."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self.temp_dir.name)

        self.static_manager = StaticAssetManager()

        # Start daemon with authentication enabled
        self.daemon = ContinuumHttpDaemon(
            workspace_root=str(self.workspace_root),
            host="127.0.0.1",
            default_port=9100,
            require_auth=True
        )
        self.status = self.daemon.start(run_in_background=True)
        self.base_url = self.status.server_url

    def tearDown(self) -> None:
        self.daemon.stop()
        self.temp_dir.cleanup()

    # --------------------------------------------------------------------------
    # 1. StaticAssetManager Unit Tests
    # --------------------------------------------------------------------------
    def test_static_asset_manager_resolution(self) -> None:
        """Verifies resolution of index.html, dashboard.css, and dashboard.js."""
        # Root path resolution
        res_root = self.static_manager.resolve_asset("/")
        self.assertIsNotNone(res_root)
        content_root, mime_root = res_root
        self.assertIn(b"CONTINUUM", content_root)
        self.assertIn("text/html", mime_root)

        # CSS resolution
        res_css = self.static_manager.resolve_asset("/dashboard.css")
        self.assertIsNotNone(res_css)
        content_css, mime_css = res_css
        self.assertIn(b"--bg-primary", content_css)
        self.assertIn("text/css", mime_css)

        # JS resolution
        res_js = self.static_manager.resolve_asset("/dashboard.js")
        self.assertIsNotNone(res_js)
        content_js, mime_js = res_js
        self.assertIn(b"ContinuumDashboardApp", content_js)
        self.assertIn("application/javascript", mime_js)

    def test_directory_traversal_guard(self) -> None:
        """Verifies directory traversal attempts are safely rejected."""
        self.assertIsNone(self.static_manager.resolve_asset("/../routes.py"))
        self.assertIsNone(self.static_manager.resolve_asset("/../../pyproject.toml"))
        self.assertIsNone(self.static_manager.resolve_asset("/..\\..\\pyproject.toml"))

    def test_mime_type_mapping(self) -> None:
        """Verifies MIME type mapping for all core web asset extensions."""
        self.assertEqual(self.static_manager.get_mime_type("app.html"), "text/html; charset=utf-8")
        self.assertEqual(self.static_manager.get_mime_type("style.css"), "text/css; charset=utf-8")
        self.assertEqual(self.static_manager.get_mime_type("script.js"), "application/javascript; charset=utf-8")
        self.assertEqual(self.static_manager.get_mime_type("logo.svg"), "image/svg+xml")
        self.assertEqual(self.static_manager.get_mime_type("icon.png"), "image/png")

    # --------------------------------------------------------------------------
    # 2. End-to-End HTTP Daemon Serving Tests
    # --------------------------------------------------------------------------
    def test_http_root_serves_dashboard_html(self) -> None:
        """GET / returns HTML dashboard without requiring auth token."""
        req = urllib.request.Request(f"{self.base_url}/")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.headers.get("Content-Type", ""))
            body = resp.read().decode("utf-8")
            self.assertIn("Continuum — AI Work Continuity Control Dashboard", body)
            self.assertIn("dashboard.css", body)
            self.assertIn("dashboard.js", body)

    def test_http_serves_css_and_js_assets(self) -> None:
        """GET /dashboard.css and /dashboard.js return correct headers and content."""
        # CSS test
        req_css = urllib.request.Request(f"{self.base_url}/dashboard.css")
        with urllib.request.urlopen(req_css, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/css", resp.headers.get("Content-Type", ""))
            body_css = resp.read().decode("utf-8")
            self.assertIn(":root", body_css)

        # JS test
        req_js = urllib.request.Request(f"{self.base_url}/dashboard.js")
        with urllib.request.urlopen(req_js, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("application/javascript", resp.headers.get("Content-Type", ""))
            body_js = resp.read().decode("utf-8")
            self.assertIn("ContinuumDashboardApp", body_js)

    def test_http_non_existent_static_returns_404(self) -> None:
        """GET /non_existent.png returns 404 Not Found."""
        req = urllib.request.Request(f"{self.base_url}/missing_asset_file.png")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5.0)
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
