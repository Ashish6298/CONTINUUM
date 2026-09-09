"""
Project Continuum - Secret Redaction and Sanitization Engine
============================================================
Ensures that credentials, API keys, private tokens, passwords, and secrets
are never collected, stored, or exposed in Continuum state or evidence.
"""

import re
from typing import Any, Dict, List, Set, Union


class SecretSanitizer:
    """
    Detects and redacts sensitive information such as API keys, tokens,
    passwords, and private keys.
    """

    # Known sensitive key substrings (case-insensitive)
    SENSITIVE_KEY_NAMES: Set[str] = {
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "access_key",
        "auth_token",
        "jwt",
        "private_key",
        "client_secret",
        "ssh_key",
        "database_url",
        "db_pass",
        "encryption_key",
        "signature",
        "credential"
    }

    # Regex patterns for common secret formats
    SECRET_VALUE_PATTERNS = [
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.DOTALL),
        re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS Access Key ID
        re.compile(r"ghp_[a-zA-Z0-9]{36}"),  # GitHub Personal Access Token
        re.compile(r"gho_[a-zA-Z0-9]{36}"),  # GitHub OAuth Access Token
        re.compile(r"glpat-[a-zA-Z0-9\-_]{20,32}"),  # GitLab Personal Access Token
        re.compile(r"sk-[a-zA-Z0-9]{32,64}"),  # OpenAI Secret Key
        re.compile(r"AIza[0-9A-Za-z\-_]{35}"),  # Google API Key
        re.compile(r"ey[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*"),  # JWT Token
        re.compile(r"[a-f0-9]{32,64}"),  # Raw Hex Key / Token
    ]

    @classmethod
    def is_sensitive_key(cls, key_name: str) -> bool:
        normalized = key_name.lower().replace("-", "_").replace(".", "_")
        return any(sensitive in normalized for sensitive in cls.SENSITIVE_KEY_NAMES)

    @classmethod
    def contains_secret_pattern(cls, value: str) -> bool:
        if not isinstance(value, str) or len(value) < 8:
            return False
        return any(pattern.search(value) for pattern in cls.SECRET_VALUE_PATTERNS)

    @classmethod
    def sanitize_value(cls, key: str, value: Any) -> Any:
        if cls.is_sensitive_key(key):
            return "<REDACTED_SECRET>"
        if isinstance(value, str):
            for pattern in cls.SECRET_VALUE_PATTERNS:
                if pattern.search(value):
                    return "<REDACTED_SECRET>"
            return value
        elif isinstance(value, dict):
            return cls.sanitize_dict(value)
        elif isinstance(value, list):
            return [cls.sanitize_value(key, item) for item in value]
        return value

    @classmethod
    def sanitize_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = {}
        for k, v in data.items():
            if cls.is_sensitive_key(k):
                sanitized[k] = "<REDACTED_SECRET>"
            elif isinstance(v, dict):
                sanitized[k] = cls.sanitize_dict(v)
            elif isinstance(v, list):
                sanitized[k] = [cls.sanitize_value(k, item) for item in v]
            elif isinstance(v, str):
                sanitized[k] = cls.sanitize_value(k, v)
            else:
                sanitized[k] = v
        return sanitized
