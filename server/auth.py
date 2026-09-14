"""
Project Continuum - Authentication & CORS Origin Guard
======================================================
Milestone 26 - Phase 27: Ephemeral Handshake Authentication & CORS Origin Guard.
Provides cryptographically secure session token generation, file persistence,
token verification, and strict origin validation for authorized web platforms.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from typing import Dict, List, Optional, Set, Tuple


class SessionAuthManager:
    """
    Manages ephemeral session tokens for local Continuum daemon instances.
    Enforces restricted token file permissions and authentication handshakes.
    """

    TOKEN_FILENAME = "auth.token"

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()
        self.continuum_dir = self.workspace_root / ".continuum"
        self.token_file = self.continuum_dir / self.TOKEN_FILENAME
        self._current_token: Optional[str] = None

    def generate_token(self) -> str:
        """
        Generates an ephemeral, cryptographically secure 48-character hex token (24 bytes)
        and persists it securely to .continuum/auth.token with restricted permissions.
        """
        self.continuum_dir.mkdir(parents=True, exist_ok=True)
        token = secrets.token_hex(24)
        self._current_token = token

        # Write token file
        self.token_file.write_text(token, encoding="utf-8")

        # Restrict permissions to owner read/write only (0600 on POSIX)
        try:
            if sys.platform != "win32":
                os.chmod(self.token_file, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

        return token

    def get_token(self) -> Optional[str]:
        """Returns active token from memory or reads from .continuum/auth.token."""
        if self._current_token:
            return self._current_token
        if self.token_file.exists():
            try:
                token = self.token_file.read_text(encoding="utf-8").strip()
                if token:
                    self._current_token = token
                    return token
            except OSError:
                pass
        return None

    def verify_token(self, provided_token: Optional[str]) -> bool:
        """
        Verifies provided token against the current active session token using
        constant-time comparison to prevent timing attacks.
        """
        active = self.get_token()
        if not active or not provided_token:
            return False
        return secrets.compare_digest(active, provided_token.strip())

    def revoke_token(self) -> None:
        """Revokes the current token and removes the token file."""
        self._current_token = None
        if self.token_file.exists():
            try:
                self.token_file.unlink()
            except OSError:
                pass


class CorsOriginGuard:
    """
    Validates HTTP request origins against whitelisted local origins and
    authorized AI web platforms (ChatGPT, Claude, Google AI Studio, Gemini, DeepSeek).
    """

    # Whitelisted production AI platforms
    ALLOWED_WEB_ORIGINS: Set[str] = {
        "https://chatgpt.com",
        "https://claude.ai",
        "https://aistudio.google.com",
        "https://gemini.google.com",
        "https://chat.deepseek.com",
    }

    # Regex pattern for loopback origins on any port
    LOOPBACK_ORIGIN_REGEX = re.compile(r"^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$", re.IGNORECASE)

    @classmethod
    def is_origin_allowed(cls, origin: Optional[str]) -> bool:
        """
        Evaluates whether an Origin header is permitted to access the daemon.
        - None / Empty Origin: Permitted (same-origin, local tools, curl, standard CLI).
        - Localhost / 127.0.0.1: Permitted (local web UI dashboard).
        - Whitelisted AI Platforms: Permitted (Tampermonkey browser companion).
        - Any third-party domain: REJECTED.
        """
        if not origin:
            return True

        origin_clean = origin.strip().lower().rstrip("/")

        # Check local loopback addresses (http://localhost:8765, http://127.0.0.1:3000, etc.)
        if cls.LOOPBACK_ORIGIN_REGEX.match(origin_clean):
            return True

        # Check whitelisted web platforms
        if origin_clean in cls.ALLOWED_WEB_ORIGINS:
            return True

        return False

    @classmethod
    def get_cors_headers(cls, origin: Optional[str]) -> Dict[str, str]:
        """
        Returns appropriate CORS response headers based on the validated origin.
        """
        if not origin or not cls.is_origin_allowed(origin):
            return {}

        return {
            "Access-Control-Allow-Origin": origin.strip(),
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Continuum-Token",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Max-Age": "86400"
        }
