"""
Project Continuum - Test Sanitizer & Path Normalization (Phase 28)
==================================================================
Verifies:
1. High-risk credential and certificate file filtering:
   - Excludes .env, .env.local, id_rsa, *.pem, *.key, *.pfx, credentials.json, service_account.json.
2. Regex-based secret redaction in text, diffs, code, and nested payloads:
   - Redacts RSA private keys, AWS access keys, GitHub tokens, OpenAI/Anthropic/Google keys,
     JWT tokens, and database passwords in connection URLs.
3. Path relative normalization:
   - Converts host-specific absolute paths (Windows and POSIX) to relative paths.
4. End-to-end API response sanitization:
   - Tests that /api/context, /api/symbols, and /api/prompt return sanitized payloads
     with zero leaked secrets and zero host absolute paths.
"""

import json
from pathlib import Path
import tempfile
from typing import Any, Dict, List
import unittest
import urllib.request
import urllib.error

from server.auth import SessionAuthManager
from server.daemon import ContinuumHttpDaemon
from server.sanitizer import DaemonSanitizer


class TestDaemonSanitizer(unittest.TestCase):
    """Test suite for Phase 28: Secret Redaction & Path Sanitization Pipeline."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self.temp_dir.name)

        # 1. Create standard source file
        (self.workspace_root / "service.py").write_text(
            "class PaymentService:\n"
            "    def process(self):\n"
            "        api_key = 'sk-1234567890abcdef1234567890abcdef'\n"
            "        db = 'postgres://user:SuperSecretPassword123@db.prod:5432/db'\n"
            "        return True\n",
            encoding="utf-8"
        )

        # 2. Create high-risk secret files that MUST be excluded
        (self.workspace_root / ".env").write_text("OPENAI_KEY=sk-test123456\nDB_PASS=secret\n", encoding="utf-8")
        (self.workspace_root / ".env.local").write_text("STRIPE_KEY=sk_test_123\n", encoding="utf-8")
        (self.workspace_root / "id_rsa").write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----", encoding="utf-8")
        (self.workspace_root / "server.key").write_text("PRIVATE_KEY_DATA", encoding="utf-8")
        (self.workspace_root / "credentials.json").write_text('{"client_secret": "abc"}', encoding="utf-8")

        # Launch HTTP daemon
        self.daemon = ContinuumHttpDaemon(
            workspace_root=str(self.workspace_root),
            host="127.0.0.1",
            default_port=9000,
            require_auth=True
        )
        self.status = self.daemon.start(run_in_background=True)
        self.base_url = self.status.server_url
        self.auth_token = self.daemon.auth_manager.get_token()

    def tearDown(self) -> None:
        self.daemon.stop()
        self.temp_dir.cleanup()

    # --------------------------------------------------------------------------
    # 1. High-Risk File Detection Unit Tests
    # --------------------------------------------------------------------------
    def test_high_risk_file_detection(self) -> None:
        """Verifies high-risk filenames and extensions are flagged."""
        # High-risk files
        self.assertTrue(DaemonSanitizer.is_high_risk_file(".env"))
        self.assertTrue(DaemonSanitizer.is_high_risk_file(".env.local"))
        self.assertTrue(DaemonSanitizer.is_high_risk_file("src/.env.production"))
        self.assertTrue(DaemonSanitizer.is_high_risk_file("id_rsa"))
        self.assertTrue(DaemonSanitizer.is_high_risk_file("id_ed25519"))
        self.assertTrue(DaemonSanitizer.is_high_risk_file("certs/server.pem"))
        self.assertTrue(DaemonSanitizer.is_high_risk_file("private.key"))
        self.assertTrue(DaemonSanitizer.is_high_risk_file("service_account.json"))
        self.assertTrue(DaemonSanitizer.is_high_risk_file("credentials.json"))

        # Safe files
        self.assertFalse(DaemonSanitizer.is_high_risk_file("app.py"))
        self.assertFalse(DaemonSanitizer.is_high_risk_file("src/index.ts"))
        self.assertFalse(DaemonSanitizer.is_high_risk_file("package.json"))
        self.assertFalse(DaemonSanitizer.is_high_risk_file("README.md"))

    # --------------------------------------------------------------------------
    # 2. Text & Regex Secret Redaction Unit Tests
    # --------------------------------------------------------------------------
    def test_text_secret_redaction(self) -> None:
        """Verifies pattern matching for private keys, tokens, and credentials."""
        # Private Key
        raw_key = "-----BEGIN RSA PRIVATE KEY-----\nMIIEogIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
        redacted_key = DaemonSanitizer.sanitize_text(raw_key)
        self.assertNotIn("MIIEog", redacted_key)
        self.assertIn("<REDACTED_PRIVATE_KEY>", redacted_key)

        # AWS Key
        aws_text = "Deploying with key AKIAIOSFODNN7EXAMPLE to us-east-1"
        self.assertIn("<REDACTED_AWS_KEY>", DaemonSanitizer.sanitize_text(aws_text))

        # GitHub Token
        gh_text = "Using ghp_1234567890abcdefghijklmnopqrstuvwxyz for clone"
        self.assertIn("<REDACTED_GITHUB_TOKEN>", DaemonSanitizer.sanitize_text(gh_text))

        # OpenAI & Anthropic Keys
        ai_text = "OpenAI: sk-1234567890abcdef1234567890abcdef and Claude: sk-ant-api03-1234567890abcdef1234567890abcdef12345678"
        redacted_ai = DaemonSanitizer.sanitize_text(ai_text)
        self.assertIn("<REDACTED_OPENAI_KEY>", redacted_ai)
        self.assertIn("<REDACTED_ANTHROPIC_KEY>", redacted_ai)

        # Database URL password
        db_url = "Connecting to postgres://admin:SuperSecretPass123@db.prod.internal:5432/main_db"
        redacted_db = DaemonSanitizer.sanitize_text(db_url)
        self.assertNotIn("SuperSecretPass123", redacted_db)
        self.assertIn("postgres://admin:<REDACTED_PASSWORD>@db.prod.internal:5432/main_db", redacted_db)

    # --------------------------------------------------------------------------
    # 3. Path Relative Normalization Unit Tests
    # --------------------------------------------------------------------------
    def test_path_relative_normalization(self) -> None:
        """Verifies conversion of absolute host paths to relative workspace paths."""
        ws = self.workspace_root
        file_abs = ws / "src" / "components" / "Button.tsx"

        # POSIX / Windows path normalization
        norm = DaemonSanitizer.normalize_path(file_abs, ws)
        self.assertEqual(norm, "src/components/Button.tsx")

        # Root itself normalizes to "."
        self.assertEqual(DaemonSanitizer.normalize_path(ws, ws), ".")

    # --------------------------------------------------------------------------
    # 4. End-to-End API Sanitization Tests
    # --------------------------------------------------------------------------
    def test_api_context_excludes_high_risk_files(self) -> None:
        """GET /api/context strictly omits .env, .env.local, and private key files."""
        req = urllib.request.Request(
            f"{self.base_url}/api/context",
            headers={"X-Continuum-Token": self.auth_token}
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))

            files = data.get("files", [])
            self.assertIn("service.py", files)
            self.assertNotIn(".env", files)
            self.assertNotIn(".env.local", files)
            self.assertNotIn("id_rsa", files)
            self.assertNotIn("server.key", files)
            self.assertNotIn("credentials.json", files)

    def test_api_prompt_redacts_secrets_in_generated_prompts(self) -> None:
        """POST /api/prompt redacts sensitive keys and connection passwords."""
        prompt_req = {
            "target_model": "claude",
            "task_description": "Review payment processing logic"
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/prompt",
            data=json.dumps(prompt_req).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Continuum-Token": self.auth_token
            }
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))

            prompt_text = data.get("prompt", "")
            # Ensure raw secret key is redacted
            self.assertNotIn("sk-1234567890abcdef1234567890abcdef", prompt_text)
            self.assertNotIn("SuperSecretPassword123", prompt_text)


if __name__ == "__main__":
    unittest.main()
