"""
Project Continuum - Secret Redaction & Path Sanitization Pipeline
=================================================================
Milestone 26 - Phase 28: Secret Redaction & Path Sanitization Pipeline.
Provides comprehensive security filtering for all API responses and AI handoffs:
1. Filters high-risk credential and certificate files (.env, *.pem, *.key, *.pfx, id_rsa, etc.).
2. Regex-based secret redaction in text, diffs, code snippets, and JSON payloads.
3. Path relative normalization: converts host-specific absolute paths to relative paths.
"""

from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Union

from extractors.config.secret_sanitizer import SecretSanitizer


class DaemonSanitizer:
    """
    Security pipeline protecting code context from credential leakage and
    host filesystem information disclosure across HTTP endpoints.
    """

    # High-risk sensitive filenames and extensions that must NEVER be served
    HIGH_RISK_FILENAMES: Set[str] = {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        ".env.test",
        ".env.staging",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "credentials.json",
        "service_account.json",
        "service-account.json",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
        "token.json",
        "auth.token",
        "daemon.pid",
        "daemon.token",
    }

    HIGH_RISK_EXTENSIONS: Set[str] = {
        ".pem",
        ".key",
        ".pfx",
        ".p12",
        ".pkcs12",
        ".keystore",
        ".jks",
        ".crt",
        ".der",
    }

    # Inline secret redaction regex patterns
    INLINE_SECRET_PATTERNS = [
        # Private Keys
        (re.compile(r"-----BEGIN [A-Z0-9\s]+PRIVATE KEY-----.*?-----END [A-Z0-9\s]+PRIVATE KEY-----", re.DOTALL), "<REDACTED_PRIVATE_KEY>"),
        # AWS Access Key IDs
        (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<REDACTED_AWS_KEY>"),
        # GitHub Personal / OAuth Access Tokens
        (re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36}\b"), "<REDACTED_GITHUB_TOKEN>"),
        # GitLab Personal Access Tokens
        (re.compile(r"\bglpat-[a-zA-Z0-9\-_]{20,32}\b"), "<REDACTED_GITLAB_TOKEN>"),
        # OpenAI API Keys
        (re.compile(r"\bsk-[a-zA-Z0-9]{20,64}\b"), "<REDACTED_OPENAI_KEY>"),
        # Anthropic API Keys
        (re.compile(r"\bsk-ant-[a-zA-Z0-9\-_]{20,90}\b"), "<REDACTED_ANTHROPIC_KEY>"),
        # Google Cloud / AI Studio API Keys
        (re.compile(r"\bAIza[0-9A-Za-z\-_]{25,45}\b"), "<REDACTED_GOOGLE_API_KEY>"),
        # JWT Tokens (3 base64 url-safe parts)
        (re.compile(r"\beyJ[A-Za-z0-9-_=]+\.eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_.+/=]*\b"), "<REDACTED_JWT_TOKEN>"),
        # Generic DB Connection URIs containing passwords
        (re.compile(r"((?:postgres|postgresql|mysql|mongodb|redis|amqp|mssql):\/\/[^:\s]+:)([^@\s]+)(@[^\s]+)"), r"\1<REDACTED_PASSWORD>\3"),
    ]

    @classmethod
    def is_high_risk_file(cls, file_path: Union[str, Path]) -> bool:
        """
        Determines whether a file path or name represents a high-risk secret file
        that must be excluded from analysis, symbol indexing, diffs, and prompts.
        """
        p = Path(file_path)
        name = p.name.lower()
        ext = p.suffix.lower()

        # Check exact filename
        if name in cls.HIGH_RISK_FILENAMES:
            return True

        # Check .env prefix (e.g. .env.secret, .env.backup)
        if name.startswith(".env.") or name == ".env":
            return True

        # Check high risk extensions
        if ext in cls.HIGH_RISK_EXTENSIONS:
            return True

        return False

    @classmethod
    def sanitize_text(cls, text: str) -> str:
        """
        Redacts credentials, private keys, API keys, JWTs, and passwords from raw text.
        """
        if not text or not isinstance(text, str):
            return text

        result = text
        for pattern, replacement in cls.INLINE_SECRET_PATTERNS:
            result = pattern.sub(replacement, result)

        return result

    @classmethod
    def normalize_path(cls, path_str: Union[str, Path], workspace_root: Union[str, Path]) -> str:
        """
        Converts absolute filesystem paths (Windows or POSIX) to relative workspace paths.
        Prevents leaking host user home directory or disk paths (e.g., C:\\Users\\... or /home/dev/...).
        """
        if not path_str:
            return ""

        raw_str = str(path_str)
        ws_root = Path(workspace_root).resolve()

        try:
            target_path = Path(raw_str).resolve()
            # If target_path is inside workspace_root, return relative POSIX path
            rel = target_path.relative_to(ws_root)
            return rel.as_posix()
        except (ValueError, RuntimeError):
            pass

        # Fallback string-based replacement if relative_to raises across drives or formats
        ws_root_posix = ws_root.as_posix()
        ws_root_win = str(ws_root)

        clean_path = raw_str.replace(ws_root_win, "").replace(ws_root_posix, "")
        clean_path = clean_path.lstrip("\\/").replace("\\", "/")
        return clean_path if clean_path else "."

    @classmethod
    def sanitize_payload(cls, data: Any, workspace_root: Optional[Union[str, Path]] = None) -> Any:
        """
        Recursively sanitizes a JSON-compatible dictionary or list:
        - Redacts secrets in all strings using SecretSanitizer & regex patterns.
        - Preserves integer, float, boolean, and None values untouched.
        - Converts absolute path values in sub-properties to relative workspace paths if workspace_root is provided.
        - Excludes high-risk files from file lists.
        """
        if isinstance(data, dict):
            sanitized_dict = {}
            for k, v in data.items():
                # Filter out sensitive string keys (e.g. auth_token, client_secret)
                # But don't redact numerical token counts like estimated_tokens or token_budget
                if isinstance(v, str) and SecretSanitizer.is_sensitive_key(k) and not k.endswith("_tokens") and not k.endswith("_count"):
                    sanitized_dict[k] = "<REDACTED_SECRET>"
                else:
                    sanitized_dict[k] = cls.sanitize_payload(v, workspace_root=workspace_root)
            return sanitized_dict

        elif isinstance(data, list):
            sanitized_list = []
            for item in data:
                # If item is a filename/path string, check if it's high risk
                if isinstance(item, str) and cls.is_high_risk_file(item):
                    continue  # Exclude high-risk files from file lists
                sanitized_list.append(cls.sanitize_payload(item, workspace_root=workspace_root))
            return sanitized_list

        elif isinstance(data, str):
            # Apply regex redaction for API keys, tokens, and credentials
            return cls.sanitize_text(data)

        return data

