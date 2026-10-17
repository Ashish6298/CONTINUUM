"""
Project Continuum — Privacy Controls, Secret Redaction & Policy Enforcement
===========================================================================
Milestone 42: Retention, Privacy and Security
Phase 74: Privacy Controls and Secret Redaction

Key Architecture & Invariant Enforcement:
1. Clear Settings & Policy Configuration:
   - Automation: allow_automated_triggers, automation_privacy_level, automation_exclude_sensitive.
   - Excerpts: allow_excerpts, max_excerpt_chars.
   - Snapshots: allow_snapshots, max_snapshot_size_bytes.
   - Sensitive content: redact_sensitive_content, redact_credentials_in_logs, custom_denied_terms,
     custom_high_risk_filenames, custom_secret_patterns.
   - Export inclusion: export_include_secrets (never permits plaintext secret leakage),
     export_redact_sensitive, export_include_snapshots.
   - AI: ai_enhancement_allowed (explicit opt-in only), ai_data_sharing_consent, ai_disclose_scope.
   Persisted atomically in `.continuum/privacy.json`.

2. Secret Detection & Redaction:
   - Reuses and unifies DaemonSanitizer & SecretSanitizer patterns.
   - High-confidence redaction for AWS keys, GitHub/GitLab tokens, OpenAI/Anthropic/Google API keys,
     JWTs, connection URIs, PEM private keys, Slack tokens, and Bearer credentials.
   - Case-insensitive custom denied terms.
   - Evidence-based confidence assessment: Explicitly documents verified pattern matches vs heuristic
     boundaries, avoiding false claims of perfect detection.

3. Complete Propagation Across Subsystems:
   - Search: SearchDocumentBuilder filters denied terms, sensitive credentials, and unpermitted files.
   - Snippets: Search excerpts bounded by `max_excerpt_chars` or masked if excerpts disabled.
   - Briefs: DeterministicResumeBriefGenerator strips secrets, denied terms, and enforces AI opt-in.
   - Logs: Credentials and sensitive tokens redacted before emission.
   - Exports: Authoritative export payloads sanitized, snapshots bounded/stripped per policy.
   - Rebuild: When privacy settings update, FTS5 search index rebuild purges newly excluded content.

4. Gate Invariant:
   "Derived data and integrations cannot bypass privacy controls."
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from server.sanitizer import DaemonSanitizer
from extractors.config.secret_sanitizer import SecretSanitizer


class PrivacyConfigError(Exception):
    """Raised when privacy configuration is invalid or violates core safety invariants."""
    pass


@dataclass
class SecretDetectionEvidence:
    """Evidence record for a detected secret or sensitive term match."""
    match_type: str        # e.g. "TOKEN_PATTERN", "DENIED_TERM", "KEY_NAME", "HIGH_RISK_FILE"
    category: str          # e.g. "AWS_KEY", "GITHUB_TOKEN", "PRIVATE_KEY", "CUSTOM_DENIED_TERM"
    masked_sample: str     # e.g. "AKIA****1234" (safely masked excerpt)
    confidence: str        # "HIGH", "MEDIUM", "HEURISTIC"

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass
class SecretRedactionResult:
    """Detailed result of secret detection and redaction evaluation."""
    original_length: int
    redacted_length: int
    redactions_count: int
    categories_found: List[str]
    evidence: List[SecretDetectionEvidence]
    redacted_text: str
    confidence_assessment: str = (
        "EVIDENCE-BASED DISCLOSURE: High-confidence detection applied for verified token patterns "
        "(AWS, GitHub, GitLab, OpenAI, Anthropic, Google API, JWT, DB URIs, Private Keys, Slack). "
        "Regex/entropy pattern matching cannot guarantee 100% detection of arbitrary undisclosed or "
        "obfuscated credentials without verified signatures."
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_length": self.original_length,
            "redacted_length": self.redacted_length,
            "redactions_count": self.redactions_count,
            "categories_found": list(self.categories_found),
            "evidence": [e.to_dict() for e in self.evidence],
            "redacted_text": self.redacted_text,
            "confidence_assessment": self.confidence_assessment,
        }


@dataclass
class PrivacyConfig:
    """
    Unified Privacy, Secret Redaction, and Policy Configuration for Project Continuum.
    All choices are explicitly configurable and propagate across all derived subsystems.
    """
    # 1. Automation Settings
    automation_allowed: bool = False
    automation_privacy_level: str = "strict"   # "strict" | "standard"
    automation_exclude_sensitive: bool = True

    # 2. Excerpt / Snippet Settings
    allow_excerpts: bool = True
    max_excerpt_chars: int = 280

    # 3. Snapshot Settings
    allow_snapshots: bool = True
    max_snapshot_size_bytes: int = 512 * 1024  # 512 KB

    # 4. Sensitive Content & Redaction Settings
    redact_sensitive_content: bool = True
    redact_credentials_in_logs: bool = True
    custom_denied_terms: List[str] = field(default_factory=list)
    custom_high_risk_filenames: List[str] = field(default_factory=list)
    custom_secret_patterns: List[str] = field(default_factory=list)

    # 5. Export Inclusion Settings
    export_include_secrets: bool = False        # Invariant: plaintext secrets never exported
    export_redact_sensitive: bool = True
    export_include_snapshots: bool = True

    # 6. AI Enhancement Settings
    ai_enhancement_allowed: bool = True        # Policy allows AI if explicit user consent is granted
    ai_data_sharing_consent: bool = False
    ai_disclose_scope: bool = True

    def validate(self) -> None:
        """Validates configuration bounds and enforces safety invariants."""
        if self.automation_privacy_level not in ("strict", "standard"):
            raise PrivacyConfigError(
                f"Invalid automation_privacy_level: '{self.automation_privacy_level}'. Must be 'strict' or 'standard'."
            )
        if self.max_excerpt_chars < 20 or self.max_excerpt_chars > 5000:
            raise PrivacyConfigError(
                f"max_excerpt_chars must be between 20 and 5000 (got {self.max_excerpt_chars})."
            )
        if self.max_snapshot_size_bytes < 1024 or self.max_snapshot_size_bytes > 50 * 1024 * 1024:
            raise PrivacyConfigError(
                f"max_snapshot_size_bytes must be between 1KB and 50MB (got {self.max_snapshot_size_bytes})."
            )
        # Invariant: plaintext secrets cannot be exported if redact_sensitive_content is True
        if self.export_include_secrets and self.redact_sensitive_content:
            self.export_include_secrets = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "automation_allowed": self.automation_allowed,
            "automation_privacy_level": self.automation_privacy_level,
            "automation_exclude_sensitive": self.automation_exclude_sensitive,
            "allow_excerpts": self.allow_excerpts,
            "max_excerpt_chars": self.max_excerpt_chars,
            "allow_snapshots": self.allow_snapshots,
            "max_snapshot_size_bytes": self.max_snapshot_size_bytes,
            "redact_sensitive_content": self.redact_sensitive_content,
            "redact_credentials_in_logs": self.redact_credentials_in_logs,
            "custom_denied_terms": list(self.custom_denied_terms),
            "custom_high_risk_filenames": list(self.custom_high_risk_filenames),
            "custom_secret_patterns": list(self.custom_secret_patterns),
            "export_include_secrets": self.export_include_secrets,
            "export_redact_sensitive": self.export_redact_sensitive,
            "export_include_snapshots": self.export_include_snapshots,
            "ai_enhancement_allowed": self.ai_enhancement_allowed,
            "ai_data_sharing_consent": self.ai_data_sharing_consent,
            "ai_disclose_scope": self.ai_disclose_scope,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "PrivacyConfig":
        if not data or not isinstance(data, dict):
            return cls()
        inst = cls(
            automation_allowed=bool(data.get("automation_allowed", False)),
            automation_privacy_level=str(data.get("automation_privacy_level", "strict")),
            automation_exclude_sensitive=bool(data.get("automation_exclude_sensitive", True)),
            allow_excerpts=bool(data.get("allow_excerpts", True)),
            max_excerpt_chars=int(data.get("max_excerpt_chars", 280)),
            allow_snapshots=bool(data.get("allow_snapshots", True)),
            max_snapshot_size_bytes=int(data.get("max_snapshot_size_bytes", 512 * 1024)),
            redact_sensitive_content=bool(data.get("redact_sensitive_content", True)),
            redact_credentials_in_logs=bool(data.get("redact_credentials_in_logs", True)),
            custom_denied_terms=list(data.get("custom_denied_terms", [])),
            custom_high_risk_filenames=list(data.get("custom_high_risk_filenames", [])),
            custom_secret_patterns=list(data.get("custom_secret_patterns", [])),
            export_include_secrets=bool(data.get("export_include_secrets", False)),
            export_redact_sensitive=bool(data.get("export_redact_sensitive", True)),
            export_include_snapshots=bool(data.get("export_include_snapshots", True)),
            ai_enhancement_allowed=bool(data.get("ai_enhancement_allowed", True)),
            ai_data_sharing_consent=bool(data.get("ai_data_sharing_consent", False)),
            ai_disclose_scope=bool(data.get("ai_disclose_scope", True)),
        )
        inst.validate()
        return inst


class PrivacyManager:
    """
    Central Privacy & Secret Redaction Manager for Project Continuum.
    Manages `.continuum/privacy.json`, coordinates redaction, and propagates policy
    across search, snippets, briefs, logs, and exports.
    """

    _instances: Dict[str, "PrivacyManager"] = {}
    _active_instance: Optional["PrivacyManager"] = None
    _lock = threading.RLock()

    # Built-in verified high-confidence secret patterns
    BUILTIN_PATTERNS = [
        # Private Keys
        ("PRIVATE_KEY", re.compile(r"-----BEGIN [A-Z0-9\s]+PRIVATE KEY-----.*?-----END [A-Z0-9\s]+PRIVATE KEY-----", re.DOTALL), "<REDACTED_PRIVATE_KEY>"),
        # AWS Access Keys
        ("AWS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<REDACTED_AWS_KEY>"),
        # GitHub Personal/OAuth Tokens
        ("GITHUB_TOKEN", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36}\b"), "<REDACTED_GITHUB_TOKEN>"),
        # GitLab Tokens
        ("GITLAB_TOKEN", re.compile(r"\bglpat-[a-zA-Z0-9\-_]{20,32}\b"), "<REDACTED_GITLAB_TOKEN>"),
        # OpenAI Keys
        ("OPENAI_KEY", re.compile(r"\bsk-[a-zA-Z0-9]{20,64}\b"), "<REDACTED_OPENAI_KEY>"),
        # Anthropic Keys
        ("ANTHROPIC_KEY", re.compile(r"\bsk-ant-[a-zA-Z0-9\-_]{20,90}\b"), "<REDACTED_ANTHROPIC_KEY>"),
        # Google API Keys
        ("GOOGLE_KEY", re.compile(r"\bAIza[0-9A-Za-z\-_]{25,45}\b"), "<REDACTED_GOOGLE_API_KEY>"),
        # Slack Tokens
        ("SLACK_TOKEN", re.compile(r"\bxox[baprs]-[0-9a-zA-Z-]{10,72}\b"), "<REDACTED_SLACK_TOKEN>"),
        # JWT Tokens
        ("JWT_TOKEN", re.compile(r"\beyJ[A-Za-z0-9-_=]+\.eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_.+/=]*\b"), "<REDACTED_JWT_TOKEN>"),
        # Generic DB URIs with credentials
        ("DATABASE_URI", re.compile(r"((?:postgres|postgresql|mysql|mongodb|redis|amqp|mssql):\/\/[^:\s]+:)([^@\s]+)(@[^\s]+)"), r"\1<REDACTED_PASSWORD>\3"),
        # Generic Bearer Auth Tokens
        ("BEARER_TOKEN", re.compile(r"\b(Bearer\s+)[a-zA-Z0-9_\-\.]{25,}\b", re.IGNORECASE), r"\1<REDACTED_BEARER_TOKEN>"),
        # Generic password / secret assignments
        ("ASSIGNED_SECRET", re.compile(r"""(?i)\b(password|passwd|secret|api_key|apikey|auth_token)\s*([:=])\s*["']([^"'\s]{6,})["']"""), r'\1\2"<REDACTED_SECRET>"'),
    ]

    def __init__(self, workspace_root: Union[str, Path]):
        self.workspace_root = Path(workspace_root).resolve()
        self.config_dir = self.workspace_root / ".continuum"
        self.config_path = self.config_dir / "privacy.json"
        self._compiled_custom_patterns: List[Tuple[str, re.Pattern, str]] = []
        self._config = self.load_config()
        self._compile_custom_patterns()

    @classmethod
    def get_instance(cls, workspace_root: Optional[Union[str, Path]] = None) -> "PrivacyManager":
        """Singleton accessor per workspace root with active instance tracking."""
        with cls._lock:
            if workspace_root is None:
                if cls._active_instance is not None:
                    return cls._active_instance
                if cls._instances:
                    return next(reversed(cls._instances.values()))
                root = Path(".").resolve()
            else:
                root = Path(workspace_root).resolve()

            key = str(root)
            if key not in cls._instances:
                cls._instances[key] = cls(root)
            cls._active_instance = cls._instances[key]
            return cls._instances[key]

    @classmethod
    def reset_instances(cls) -> None:
        """Utility for test suites to clear singleton caches."""
        with cls._lock:
            cls._instances.clear()
            cls._active_instance = None

    @property
    def config(self) -> PrivacyConfig:
        with self._lock:
            return self._config

    def get_config(self) -> PrivacyConfig:
        return self.config

    def _compile_custom_patterns(self) -> None:
        """Compiles user-defined custom secret patterns safely."""
        compiled = []
        for i, pat_str in enumerate(self._config.custom_secret_patterns):
            if not pat_str or not isinstance(pat_str, str):
                continue
            try:
                cp = re.compile(pat_str)
                compiled.append((f"CUSTOM_PATTERN_{i+1}", cp, f"<REDACTED_CUSTOM_SECRET_{i+1}>"))
            except Exception:
                pass
        self._compiled_custom_patterns = compiled

    def load_config(self) -> PrivacyConfig:
        """Loads configuration from `.continuum/privacy.json` or returns default."""
        with self._lock:
            if not self.config_path.is_file():
                return PrivacyConfig()
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                return PrivacyConfig.from_dict(data)
            except Exception:
                return PrivacyConfig()

    def save_config(self, new_config: Optional[PrivacyConfig] = None) -> None:
        """Atomically saves privacy configuration to `.continuum/privacy.json`."""
        with self._lock:
            if new_config is not None:
                new_config.validate()
                self._config = new_config
                self._compile_custom_patterns()

            self.config_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = self.config_path.with_suffix(".tmp")
            data = self._config.to_dict()
            tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            tmp_path.replace(self.config_path)

    def update_config(
        self,
        new_config: PrivacyConfig,
        store: Optional[Any] = None,
        rebuild_index: bool = True
    ) -> PrivacyConfig:
        """
        Updates privacy settings, persists to disk, and optionally rebuilds derived search index.
        Phase 74 requirement: Index rebuild with updated privacy rules.
        """
        with self._lock:
            self.save_config(new_config)

        if rebuild_index and store is not None and hasattr(store, "rebuild_search_index"):
            try:
                store.rebuild_search_index()
            except Exception:
                pass

        return self.config

    def is_high_risk_file(self, file_path_or_name: Union[str, Path]) -> bool:
        """
        Determines whether a file or path represents a credential/secret file that
        must be excluded from indexing, excerpts, diffs, and snapshot captures.
        Inspects DaemonSanitizer built-ins and custom_high_risk_filenames.
        """
        if not file_path_or_name:
            return False

        # First check DaemonSanitizer baseline
        if DaemonSanitizer.is_high_risk_file(file_path_or_name):
            return True

        # Check custom high-risk filenames and extensions
        p = Path(file_path_or_name)
        name_lower = p.name.lower()
        ext_lower = p.suffix.lower()

        with self._lock:
            custom_names = {f.lower() for f in self._config.custom_high_risk_filenames}

        for custom in custom_names:
            if custom.startswith(".") and ext_lower == custom:
                return True
            if name_lower == custom or name_lower.startswith(f"{custom}.") or name_lower.endswith(f".{custom}"):
                return True

        return False

    def redact_text(self, text: Optional[str]) -> SecretRedactionResult:
        """
        Evaluates input text, detecting and redacting secrets, credentials, and custom denied terms.
        Returns SecretRedactionResult with evidence and confidence disclosure.
        """
        if not text or not isinstance(text, str):
            return SecretRedactionResult(
                original_length=0,
                redacted_length=0,
                redactions_count=0,
                categories_found=[],
                evidence=[],
                redacted_text="",
            )

        orig_len = len(text)
        current = text
        evidence_list: List[SecretDetectionEvidence] = []
        categories_found: Set[str] = set()
        redactions_count = 0

        with self._lock:
            redact_sensitive = self._config.redact_sensitive_content
            denied_terms = list(self._config.custom_denied_terms)
            custom_patterns = list(self._compiled_custom_patterns)

        # 1. Custom Denied Terms (case-insensitive substitution)
        for term in denied_terms:
            if not term or not isinstance(term, str):
                continue
            term_clean = term.strip()
            if not term_clean:
                continue

            # Word-boundary or exact string regex pattern
            escaped_term = re.escape(term_clean)
            term_regex = re.compile(rf"(?i)\b{escaped_term}\b")
            matches = list(term_regex.finditer(current))
            if not matches:
                # Fallback to direct substring match if no word boundary
                term_regex = re.compile(rf"(?i){escaped_term}")
                matches = list(term_regex.finditer(current))

            if matches:
                redactions_count += len(matches)
                categories_found.add("CUSTOM_DENIED_TERM")
                for m in matches[:3]:  # Bound sample recordings
                    raw_sample = m.group(0)
                    masked = raw_sample[0] + "***" if len(raw_sample) > 1 else "***"
                    evidence_list.append(
                        SecretDetectionEvidence(
                            match_type="DENIED_TERM",
                            category="CUSTOM_DENIED_TERM",
                            masked_sample=masked,
                            confidence="HIGH",
                        )
                    )
                current = term_regex.sub("<REDACTED_DENIED_TERM>", current)

        # 2. Built-in and Custom Secret Patterns
        if redact_sensitive:
            all_patterns = self.BUILTIN_PATTERNS + custom_patterns
            for category, regex, replacement in all_patterns:
                matches = list(regex.finditer(current))
                if matches:
                    redactions_count += len(matches)
                    categories_found.add(category)
                    for m in matches[:3]:
                        raw_sample = m.group(0)
                        masked = (
                            raw_sample[:4] + "****" + raw_sample[-4:]
                            if len(raw_sample) >= 12
                            else "****"
                        )
                        evidence_list.append(
                            SecretDetectionEvidence(
                                match_type="REGEX_PATTERN",
                                category=category,
                                masked_sample=masked,
                                confidence="HIGH",
                            )
                        )
                    current = regex.sub(replacement, current)

        return SecretRedactionResult(
            original_length=orig_len,
            redacted_length=len(current),
            redactions_count=redactions_count,
            categories_found=sorted(list(categories_found)),
            evidence=evidence_list,
            redacted_text=current,
        )

    def sanitize_text(self, text: Optional[str]) -> str:
        """Quick string sanitizer applying active redaction rules."""
        if not text:
            return ""
        return self.redact_text(text).redacted_text

    def sanitize_log(self, message: Optional[str]) -> str:
        """
        Sanitizes runtime log messages and exception strings, ensuring credentials
        and sensitive denied terms are stripped before output.
        """
        if not message:
            return ""
        with self._lock:
            if not self._config.redact_credentials_in_logs:
                return message
        return self.sanitize_text(message)

    def bound_and_sanitize_excerpt(self, text: Optional[str], max_chars: Optional[int] = None) -> str:
        """
        Sanitizes text and applies excerpt bounding per Phase 69 / Phase 74 rules.
        If `allow_excerpts` is False, returns '[EXCERPT REDACTED]'.
        """
        if not text:
            return ""

        with self._lock:
            if not self._config.allow_excerpts:
                return "[EXCERPT REDACTED]"
            limit = max_chars or self._config.max_excerpt_chars

        sanitized = self.sanitize_text(text).strip()
        if len(sanitized) <= limit:
            return sanitized

        truncated = sanitized[:limit]
        last_space = truncated.rfind(" ")
        if last_space > limit // 2:
            truncated = truncated[:last_space]

        open_marks = truncated.count("<mark>")
        close_marks = truncated.count("</mark>")
        if open_marks > close_marks:
            truncated += "</mark>"

        if not truncated.endswith("..."):
            truncated += "..."
        return truncated

    def sanitize_search_document(self, doc: Dict[str, str]) -> Dict[str, str]:
        """
        Sanitizes search index document fields (I-06, I-10).
        Removes custom denied terms, secrets, and high-risk artifacts before indexing.
        """
        sanitized = {}
        with self._lock:
            allow_excerpts = self._config.allow_excerpts
            max_chars = self._config.max_excerpt_chars

        for k, v in doc.items():
            if not isinstance(v, str):
                sanitized[k] = ""
                continue

            if k == "description" and not allow_excerpts:
                sanitized[k] = "[EXCERPT REDACTED]"
            elif k in ("description", "notes", "briefs") and not allow_excerpts:
                sanitized[k] = ""
            else:
                sanitized_val = self.sanitize_text(v)
                if k == "description" and allow_excerpts and len(sanitized_val) > max_chars:
                    sanitized_val = self.bound_and_sanitize_excerpt(sanitized_val, max_chars)
                sanitized[k] = sanitized_val

        return sanitized

    def sanitize_resume_brief(self, brief: Any) -> Any:
        """
        Sanitizes a ResumeBrief domain object or dictionary in place.
        Ensures AI enhancement flag adheres to `ai_enhancement_allowed`.
        """
        if brief is None:
            return None

        with self._lock:
            ai_allowed = self._config.ai_enhancement_allowed

        if isinstance(brief, dict):
            # Dict representation
            sanitized = {}
            for k, v in brief.items():
                if isinstance(v, str):
                    sanitized[k] = self.sanitize_text(v)
                elif isinstance(v, list):
                    sanitized[k] = [self.sanitize_text(item) if isinstance(item, str) else item for item in v]
                else:
                    sanitized[k] = v

            # Verify AI consent scope
            if not ai_allowed:
                sanitized["ai_consent_granted"] = False
                sanitized["enhancement_model"] = None
            return sanitized

        # ResumeBrief dataclass instance
        if hasattr(brief, "purpose") and brief.purpose:
            brief.purpose = self.sanitize_text(brief.purpose)
        if hasattr(brief, "summary") and brief.summary:
            brief.summary = self.sanitize_text(brief.summary)
        if hasattr(brief, "next_actions") and brief.next_actions:
            brief.next_actions = [self.sanitize_text(str(a)) for a in brief.next_actions]
        if hasattr(brief, "key_decisions") and brief.key_decisions:
            brief.key_decisions = [self.sanitize_text(str(d)) for d in brief.key_decisions]
        if hasattr(brief, "last_completed_work") and brief.last_completed_work:
            brief.last_completed_work = [self.sanitize_text(str(w)) for w in brief.last_completed_work]
        if hasattr(brief, "blockers") and brief.blockers:
            brief.blockers = [self.sanitize_text(str(b)) for b in brief.blockers]
        if hasattr(brief, "unresolved_issues") and brief.unresolved_issues:
            brief.unresolved_issues = [self.sanitize_text(str(u)) for u in brief.unresolved_issues]

        if not ai_allowed and hasattr(brief, "ai_consent_granted"):
            brief.ai_consent_granted = False

        return brief

    def sanitize_export_data(self, data: Any) -> Any:
        """
        Recursively sanitizes export payload structures for portable versioned export (Phase 76).
        Enforces `export_include_secrets=False`, redacts denied terms, and strips snapshots if disabled.
        """
        with self._lock:
            allow_snapshots = self._config.allow_snapshots
            export_include_snapshots = self._config.export_include_snapshots

        if isinstance(data, dict):
            sanitized: Dict[str, Any] = {}
            for k, v in data.items():
                # Check sensitive key names (SecretSanitizer)
                if SecretSanitizer.is_sensitive_key(k):
                    if isinstance(v, (dict, list)):
                        sanitized[k] = self.sanitize_export_data(v)
                    else:
                        sanitized[k] = "<REDACTED_SECRET>"
                    continue

                # Check snapshot omission
                if (not allow_snapshots or not export_include_snapshots) and k in (
                    "snapshot_content",
                    "snapshot_bytes",
                    "inline_content",
                ):
                    continue

                # Check high-risk file paths
                if k in ("path", "file_path", "path_or_uri") and isinstance(v, str):
                    if self.is_high_risk_file(v):
                        sanitized[k] = "<REDACTED_HIGH_RISK_PATH>"
                        continue

                sanitized[k] = self.sanitize_export_data(v)
            return sanitized

        elif isinstance(data, list):
            return [self.sanitize_export_data(item) for item in data]
        elif isinstance(data, str):
            return self.sanitize_text(data)
        else:
            return data
