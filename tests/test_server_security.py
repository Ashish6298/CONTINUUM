"""
Project Continuum - Test Authentication & CORS Guard (Phase 27)
===============================================================
Verifies:
1. SessionAuthManager generates 48-char tokens, persists to .continuum/auth.token,
   enforces constant-time verification, and revokes cleanly.
2. CorsOriginGuard permits localhost, 127.0.0.1, and authorized web AI platforms
   (ChatGPT, Claude, Google AI Studio, Gemini, DeepSeek), while strictly rejecting
   unauthorized third-party domains (e.g., https://malicious-site.com).
3. HTTP Endpoints require authentication:
   - Returns 401 Unauthorized when token is missing or invalid.
   - Accepts X-Continuum-Token header, Bearer Authorization, or ?token= query param.
4. CORS preflight OPTIONS returns 204 with valid Access-Control-* headers for
   whitelisted origins, and 403 Forbidden for unauthorized web domains.
"""

import json
from pathlib import Path
import tempfile
import time
from typing import Any, Dict, Optional
import unittest
import urllib.request
import urllib.error

from server.auth import CorsOriginGuard, SessionAuthManager
from server.daemon import ContinuumHttpDaemon


class TestAuthAndCorsGuard(unittest.TestCase):
    """Test suite for Phase 27: Ephemeral Handshake Authentication & CORS Origin Guard."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self.temp_dir.name)

        # Create sample file
        (self.workspace_root / "sample.py").write_text("def ping(): return 'pong'\n", encoding="utf-8")

        # Launch daemon with authentication enabled
        self.daemon = ContinuumHttpDaemon(
            workspace_root=str(self.workspace_root),
            host="127.0.0.1",
            default_port=8980,
            require_auth=True
        )
        self.status = self.daemon.start(run_in_background=True)
        self.base_url = self.status.server_url
        self.auth_token = self.daemon.auth_manager.get_token()

    def tearDown(self) -> None:
        self.daemon.stop()
        self.temp_dir.cleanup()

    # --------------------------------------------------------------------------
    # 1. SessionAuthManager Unit Tests
    # --------------------------------------------------------------------------
    def test_session_auth_token_generation_and_verification(self) -> None:
        """Verifies token generation, file persistence, and constant-time validation."""
        auth_mgr = SessionAuthManager(self.workspace_root)
        token = auth_mgr.generate_token()
        self.assertIsNotNone(token)
        self.assertEqual(len(token), 48)  # 24 bytes hex = 48 chars
        self.assertTrue(auth_mgr.token_file.exists())
        self.assertEqual(auth_mgr.token_file.read_text(encoding="utf-8").strip(), token)

        # Verification tests
        self.assertTrue(auth_mgr.verify_token(token))
        self.assertTrue(auth_mgr.verify_token(f"  {token}  "))
        self.assertFalse(auth_mgr.verify_token("invalid_token_1234567890abcdef"))
        self.assertFalse(auth_mgr.verify_token(None))
        self.assertFalse(auth_mgr.verify_token(""))

        # Revocation
        auth_mgr.revoke_token()
        self.assertFalse(auth_mgr.token_file.exists())
        self.assertIsNone(auth_mgr.get_token())

    # --------------------------------------------------------------------------
    # 2. CorsOriginGuard Unit Tests
    # --------------------------------------------------------------------------
    def test_cors_origin_whitelist_validation(self) -> None:
        """Verifies permitted vs blocked CORS origins."""
        # Allowed origins
        self.assertTrue(CorsOriginGuard.is_origin_allowed(None))
        self.assertTrue(CorsOriginGuard.is_origin_allowed(""))
        self.assertTrue(CorsOriginGuard.is_origin_allowed("http://localhost:8765"))
        self.assertTrue(CorsOriginGuard.is_origin_allowed("http://127.0.0.1:3000"))
        self.assertTrue(CorsOriginGuard.is_origin_allowed("https://chatgpt.com"))
        self.assertTrue(CorsOriginGuard.is_origin_allowed("https://claude.ai"))
        self.assertTrue(CorsOriginGuard.is_origin_allowed("https://aistudio.google.com"))
        self.assertTrue(CorsOriginGuard.is_origin_allowed("https://gemini.google.com"))
        self.assertTrue(CorsOriginGuard.is_origin_allowed("https://chat.deepseek.com"))

        # Blocked origins
        self.assertFalse(CorsOriginGuard.is_origin_allowed("https://malicious-site.com"))
        self.assertFalse(CorsOriginGuard.is_origin_allowed("http://evil-hacker.org"))
        self.assertFalse(CorsOriginGuard.is_origin_allowed("https://unauthorized-domain.io"))

    # --------------------------------------------------------------------------
    # 3. HTTP Authentication Tests
    # --------------------------------------------------------------------------
    def test_authenticated_api_request_success(self) -> None:
        """GET /api/status succeeds when valid token is supplied via X-Continuum-Token."""
        req = urllib.request.Request(
            f"{self.base_url}/api/status",
            headers={"X-Continuum-Token": self.auth_token}
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "online")

    def test_bearer_authorization_header_success(self) -> None:
        """GET /api/status succeeds with Authorization: Bearer <token>."""
        req = urllib.request.Request(
            f"{self.base_url}/api/status",
            headers={"Authorization": f"Bearer {self.auth_token}"}
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)

    def test_query_parameter_token_success(self) -> None:
        """GET /api/status succeeds with ?token=<token> query parameter."""
        req = urllib.request.Request(f"{self.base_url}/api/status?token={self.auth_token}")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)

    def test_missing_or_invalid_token_returns_401(self) -> None:
        """Requests without valid token return 401 Unauthorized."""
        # Missing token
        req_missing = urllib.request.Request(f"{self.base_url}/api/status")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_missing)
        self.assertEqual(ctx.exception.code, 401)

        # Invalid token
        req_invalid = urllib.request.Request(
            f"{self.base_url}/api/status",
            headers={"X-Continuum-Token": "bogus_token_12345"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_invalid)
        self.assertEqual(ctx.exception.code, 401)

    # --------------------------------------------------------------------------
    # 4. HTTP CORS Tests
    # --------------------------------------------------------------------------
    def test_cors_preflight_and_headers_for_chatgpt(self) -> None:
        """OPTIONS preflight from https://chatgpt.com returns 204 with CORS headers."""
        req = urllib.request.Request(
            f"{self.base_url}/api/status",
            headers={"Origin": "https://chatgpt.com"},
            method="OPTIONS"
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 204)
            self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "https://chatgpt.com")
            self.assertIn("X-Continuum-Token", resp.headers.get("Access-Control-Allow-Headers", ""))

    def test_cors_rejection_for_unauthorized_origin(self) -> None:
        """OPTIONS preflight or GET request from unauthorized origin returns 403 Forbidden."""
        # Preflight rejection
        req_opt = urllib.request.Request(
            f"{self.base_url}/api/status",
            headers={"Origin": "https://malicious-site.com"},
            method="OPTIONS"
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_opt)
        self.assertEqual(ctx.exception.code, 403)

        # Direct GET request rejection
        req_get = urllib.request.Request(
            f"{self.base_url}/api/status",
            headers={
                "Origin": "https://malicious-site.com",
                "X-Continuum-Token": self.auth_token
            }
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_get)
        self.assertEqual(ctx.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
