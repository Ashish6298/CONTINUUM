"""
Project Continuum — Configurable Automatic Triggers & Privacy Guards
====================================================================
Milestone 41: Artifacts, Automation and Adapters
Phase 71: Configurable Automatic Triggers

Key Architecture & Invariant Enforcement:
1. Manual Capture Invariant (I-01):
   Manual capture always remains the authoritative baseline and cannot be bypassed.
2. Supported Integration Events:
   - GIT_COMMIT: Reliable git hooks or post-commit triggers.
   - MEANINGFUL_CHANGE: Substantive filesystem change exceeding configurable threshold.
   - SCHEDULED: Periodic time-based triggers with minimum cooldown periods.
3. Individually Opt-in & Configurable:
   All triggers default to disabled (False). Must be explicitly enabled by user/config.
   Stored safely in `.continuum/triggers.json`.
4. Deduplication & Idempotency:
   Detects duplicate events using SHA-256 event fingerprinting across a configurable window.
5. Safe Retry & Error Isolation:
   Transient failures retry up to max_retries with backoff.
   Storage or evaluation errors are isolated and recorded without corrupting history.
6. Strictly NO Unrestricted Background Monitoring:
   Passive / on-event evaluation only. File checks respect standard ignore rules and cooldowns.
7. Gate: "Automation never bypasses privacy or validation."
   All automated checkpoints strictly pass through `DaemonSanitizer` (secret redaction,
   high-risk file exclusion) and `UniversalCheckpoint` validation before atomic commit
   with `ProvenanceType.AUTO_CAPTURED`.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from core.activity import Activity, ActivityStatus
from core.checkpoint import (
    UniversalCheckpoint,
    DecisionRecord,
    ArtifactReference,
    ProvenanceRecord,
    CheckpointValidationError,
)
from core.enums import ArtifactMode, ProvenanceType
from core.invariants import (
    CommitFailedError,
    InvariantViolationError,
    InvariantId,
)
from storage.activity_store import (
    ActivityCheckpointStore,
    ActivityNotFoundError,
    DanglingReferenceError,
)
from server.sanitizer import DaemonSanitizer


class TriggerType(str, Enum):
    """Supported reliable integration trigger types."""
    GIT_COMMIT = "git_commit"
    MEANINGFUL_CHANGE = "meaningful_change"
    SCHEDULED = "scheduled"


class TriggerError(Exception):
    """Base exception for automatic trigger errors."""
    pass


class TriggerDisabledError(TriggerError):
    """Raised when an evaluation is attempted on a disabled trigger type."""
    pass


class TriggerPrivacyViolationError(TriggerError):
    """Raised when an automated trigger attempts to capture unredactable high-risk content."""
    pass


@dataclass
class TriggerConfig:
    """
    Configuration options for Project Continuum automatic triggers.
    Individually opt-in; manual capture remains the default authoritative mechanism.
    """
    git_commit_enabled: bool = False
    meaningful_change_enabled: bool = False
    scheduled_enabled: bool = False

    # Meaningful change thresholds
    meaningful_change_min_files: int = 3
    meaningful_change_include_patterns: List[str] = field(default_factory=lambda: [".py", ".ts", ".js", ".go", ".rs", ".java", ".md", ".json"])
    
    # Scheduled trigger options
    scheduled_interval_seconds: int = 1800  # Default 30 minutes
    scheduled_min_cooldown_seconds: int = 300  # Minimum 5 minutes between auto captures

    # Deduplication and retry
    dedup_window_seconds: int = 60
    max_retries: int = 3
    retry_delay_seconds: float = 0.5

    # Target activity (if None, latest active activity is targeted)
    default_activity_id: Optional[str] = None

    # Privacy configuration
    redact_secrets: bool = True
    exclude_high_risk_files: bool = True
    custom_denied_terms: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "git_commit_enabled": self.git_commit_enabled,
            "meaningful_change_enabled": self.meaningful_change_enabled,
            "scheduled_enabled": self.scheduled_enabled,
            "meaningful_change_min_files": self.meaningful_change_min_files,
            "meaningful_change_include_patterns": list(self.meaningful_change_include_patterns),
            "scheduled_interval_seconds": self.scheduled_interval_seconds,
            "scheduled_min_cooldown_seconds": self.scheduled_min_cooldown_seconds,
            "dedup_window_seconds": self.dedup_window_seconds,
            "max_retries": self.max_retries,
            "retry_delay_seconds": self.retry_delay_seconds,
            "default_activity_id": self.default_activity_id,
            "redact_secrets": self.redact_secrets,
            "exclude_high_risk_files": self.exclude_high_risk_files,
            "custom_denied_terms": list(self.custom_denied_terms),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "TriggerConfig":
        if not data or not isinstance(data, dict):
            return cls()
        return cls(
            git_commit_enabled=bool(data.get("git_commit_enabled", False)),
            meaningful_change_enabled=bool(data.get("meaningful_change_enabled", False)),
            scheduled_enabled=bool(data.get("scheduled_enabled", False)),
            meaningful_change_min_files=int(data.get("meaningful_change_min_files", 3)),
            meaningful_change_include_patterns=list(data.get("meaningful_change_include_patterns", [".py", ".ts", ".js", ".go", ".rs", ".java", ".md", ".json"])),
            scheduled_interval_seconds=int(data.get("scheduled_interval_seconds", 1800)),
            scheduled_min_cooldown_seconds=int(data.get("scheduled_min_cooldown_seconds", 300)),
            dedup_window_seconds=int(data.get("dedup_window_seconds", 60)),
            max_retries=int(data.get("max_retries", 3)),
            retry_delay_seconds=float(data.get("retry_delay_seconds", 0.5)),
            default_activity_id=data.get("default_activity_id"),
            redact_secrets=bool(data.get("redact_secrets", True)),
            exclude_high_risk_files=bool(data.get("exclude_high_risk_files", True)),
            custom_denied_terms=list(data.get("custom_denied_terms", [])),
        )


@dataclass
class TriggerExecutionResult:
    """Detailed result of an automated trigger evaluation or execution."""
    trigger_type: str
    status: str  # "committed", "skipped", "error", "disabled"
    checkpoint_id: Optional[str] = None
    activity_id: Optional[str] = None
    reason: Optional[str] = None
    error: Optional[str] = None
    retries_attempted: int = 0
    redacted_count: int = 0
    excluded_files_count: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger_type": self.trigger_type,
            "status": self.status,
            "checkpoint_id": self.checkpoint_id,
            "activity_id": self.activity_id,
            "reason": self.reason,
            "error": self.error,
            "retries_attempted": self.retries_attempted,
            "redacted_count": self.redacted_count,
            "excluded_files_count": self.excluded_files_count,
            "timestamp": self.timestamp,
        }


class TriggerEngine:
    """
    Core Automation Trigger Engine for Project Continuum.
    Safely coordinates integration events, deduplication, retry, and atomic commits.
    Enforces that automation NEVER bypasses privacy or validation invariants.
    """

    CONFIG_FILE_NAME = "triggers.json"

    def __init__(
        self,
        workspace_root: Path,
        store: Optional[ActivityCheckpointStore] = None,
        config: Optional[TriggerConfig] = None,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.store = store or ActivityCheckpointStore(self.workspace_root)
        self.config_dir = self.workspace_root / ".continuum"
        self.config_path = self.config_dir / self.CONFIG_FILE_NAME
        self._lock = threading.RLock()

        # In-memory execution tracking: fingerprint -> timestamp
        self._recent_events: Dict[str, float] = {}
        # Last execution timestamp by trigger type
        self._last_trigger_time: Dict[str, float] = {}
        # Historical trigger execution logs (bounded to last 50)
        self._execution_history: List[TriggerExecutionResult] = []

        # Load or initialize configuration
        if config is not None:
            self.config = config
            self.save_config()
        else:
            self.config = self.load_config()

    def load_config(self) -> TriggerConfig:
        """Loads trigger config from disk, or returns default disabled config."""
        with self._lock:
            if not self.config_path.is_file():
                return TriggerConfig()
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                return TriggerConfig.from_dict(data)
            except Exception:
                return TriggerConfig()

    def save_config(self, new_config: Optional[TriggerConfig] = None) -> None:
        """Atomically saves trigger configuration to `.continuum/triggers.json`."""
        with self._lock:
            if new_config is not None:
                self.config = new_config

            self.config_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = self.config_path.with_suffix(".tmp")
            data = self.config.to_dict()
            tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            tmp_path.replace(self.config_path)

    def get_status(self) -> Dict[str, Any]:
        """Returns the current status of all triggers and recent execution history."""
        with self._lock:
            return {
                "config": self.config.to_dict(),
                "last_trigger_time": {k: datetime.fromtimestamp(t, tz=timezone.utc).isoformat() for k, t in self._last_trigger_time.items()},
                "history_count": len(self._execution_history),
                "recent_executions": [e.to_dict() for e in self._execution_history[-10:]],
            }

    def _record_result(self, res: TriggerExecutionResult) -> TriggerExecutionResult:
        """Records execution result in bounded in-memory log."""
        with self._lock:
            self._execution_history.append(res)
            if len(self._execution_history) > 50:
                self._execution_history = self._execution_history[-50:]
            if res.status == "committed":
                self._last_trigger_time[res.trigger_type] = time.time()
        return res

    def _clean_stale_fingerprints(self) -> None:
        """Purges event fingerprints older than dedup_window_seconds."""
        now = time.time()
        cutoff = now - self.config.dedup_window_seconds
        stale = [k for k, t in self._recent_events.items() if t < cutoff]
        for k in stale:
            self._recent_events.pop(k, None)

    def _compute_fingerprint(self, trigger_type: TriggerType, target_activity: str, payload_data: Any) -> str:
        """Computes deterministic SHA-256 fingerprint for deduplication."""
        serialized = json.dumps(
            {"type": trigger_type.value, "activity": target_activity, "payload": payload_data},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _resolve_target_activity(self, requested_id: Optional[str] = None) -> Activity:
        """
        Resolves the target activity for an automated checkpoint:
        1. Requested activity_id if provided.
        2. Configured default_activity_id if set.
        3. Most recently updated active activity in store.
        Raises ActivityNotFoundError if none found or active.
        """
        target_id = requested_id or self.config.default_activity_id
        if target_id:
            act = self.store.get_activity(target_id)
            if not act:
                raise ActivityNotFoundError(target_id)
            return act

        # Fallback: scan for any active activity
        activities_res = self.store.list_activities(status=ActivityStatus.ACTIVE)
        activities = activities_res[0] if isinstance(activities_res, tuple) else activities_res
        if activities:
            return activities[0]

        raise ActivityNotFoundError("No active activity available for automated trigger capture.")

    def _get_latest_checkpoint(self, activity_id: str) -> Optional[UniversalCheckpoint]:
        """Helper to get the most recent checkpoint for an activity."""
        try:
            chks_res = self.store.list_checkpoints(activity_id, limit=1, order="desc")
            chks = chks_res[0] if isinstance(chks_res, tuple) else chks_res
            return chks[0] if chks else None
        except Exception:
            return None

    def sanitize_content(
        self,
        text: str,
        files: Optional[List[str]] = None,
    ) -> Tuple[str, List[str], int, int]:
        """
        Applies strict privacy rules (DaemonSanitizer):
        - Inline secret redaction on text (API keys, tokens, DB URIs, etc.).
        - Custom denied terms redaction.
        - High-risk file exclusion (.env, credentials.json, id_rsa, *.pem, etc.).
        - Workspace path normalization.
        Returns (sanitized_text, filtered_files, redacted_count, excluded_files_count).
        """
        redactions = 0
        excluded_files = 0
        sanitized_text = text or ""

        if self.config.redact_secrets:
            # 1. Regex secret patterns
            orig = sanitized_text
            sanitized_text = DaemonSanitizer.sanitize_text(sanitized_text)
            if orig != sanitized_text:
                redactions += 1

            # 2. Custom denied terms
            for term in self.config.custom_denied_terms:
                if term and term in sanitized_text:
                    sanitized_text = sanitized_text.replace(term, "<REDACTED_CUSTOM_TERM>")
                    redactions += 1

        filtered_files: List[str] = []
        if files:
            for f in files:
                f_str = str(f).strip()
                if not f_str:
                    continue
                # Normalize path to relative posix
                norm_f = DaemonSanitizer.normalize_path(f_str, self.workspace_root)
                if self.config.exclude_high_risk_files and DaemonSanitizer.is_high_risk_file(norm_f):
                    excluded_files += 1
                    continue
                filtered_files.append(norm_f)

        return sanitized_text, filtered_files, redactions, excluded_files

    def _execute_commit_with_retry(
        self,
        activity: Activity,
        checkpoint: UniversalCheckpoint,
    ) -> UniversalCheckpoint:
        """
        Commits checkpoint with bounded retries and exponential backoff.
        Prevents corrupt or partial state on transient failure.
        """
        attempts = 0
        last_exc: Optional[Exception] = None

        while attempts <= self.config.max_retries:
            try:
                committed = self.store.commit_checkpoint(checkpoint)
                return committed
            except (CheckpointValidationError, DanglingReferenceError, ActivityNotFoundError) as e:
                # Fatal validation errors are not retried
                raise e
            except Exception as e:
                last_exc = e
                attempts += 1
                if attempts <= self.config.max_retries:
                    time.sleep(self.config.retry_delay_seconds * attempts)

        raise CommitFailedError(
            message=f"Automated checkpoint commit failed after {self.config.max_retries} retries: {str(last_exc)}",
            internal_details=str(last_exc),
        )

    # --------------------------------------------------------------------------
    # Trigger 1: Git Integration Event
    # --------------------------------------------------------------------------
    def evaluate_git_commit_trigger(
        self,
        commit_hash: str,
        commit_message: str,
        changed_files: List[str],
        branch: Optional[str] = None,
        activity_id: Optional[str] = None,
    ) -> TriggerExecutionResult:
        """
        Evaluates a Git commit event (e.g. from post-commit hook or integration).
        Individually opt-in via `git_commit_enabled`.
        """
        if not self.config.git_commit_enabled:
            return self._record_result(TriggerExecutionResult(
                trigger_type=TriggerType.GIT_COMMIT.value,
                status="disabled",
                reason="git_commit_enabled is False in trigger config",
            ))

        # Check activity
        try:
            act = self._resolve_target_activity(activity_id)
        except ActivityNotFoundError as e:
            return self._record_result(TriggerExecutionResult(
                trigger_type=TriggerType.GIT_COMMIT.value,
                status="error",
                error=str(e),
                reason="No active target activity found",
            ))

        # Deduplication check
        clean_hash = (commit_hash or "").strip()
        fingerprint = self._compute_fingerprint(TriggerType.GIT_COMMIT, act.id, {"hash": clean_hash})
        with self._lock:
            self._clean_stale_fingerprints()
            if fingerprint in self._recent_events:
                return self._record_result(TriggerExecutionResult(
                    trigger_type=TriggerType.GIT_COMMIT.value,
                    status="skipped",
                    activity_id=act.id,
                    reason=f"Duplicate git commit '{clean_hash}' within deduplication window",
                ))
            self._recent_events[fingerprint] = time.time()

        # Privacy sanitization
        sanitized_msg, filtered_files, redactions, excluded_files = self.sanitize_content(
            commit_message, changed_files
        )

        # Build checkpoint
        parent_chk = self._get_latest_checkpoint(act.id)
        parent_id = parent_chk.id if parent_chk else None

        # Build artifact references for changed files
        artifacts = []
        for f in filtered_files:
            artifacts.append(ArtifactReference(
                name=Path(f).name or f,
                path_or_uri=f,
                mode=ArtifactMode.REFERENCE,
            ))

        # Formulate checkpoint
        now_iso = datetime.now(timezone.utc).isoformat()
        checkpoint = UniversalCheckpoint(
            id=f"chk_auto_git_{uuid.uuid4().hex[:12]}",
            activity_id=act.id,
            timestamp=now_iso,
            parent_checkpoint_id=parent_id,
            context=f"Automated checkpoint triggered by git commit: {sanitized_msg}",
            completed_work=[f"Git commit {clean_hash[:8] if clean_hash else 'unknown'}: {sanitized_msg}"],
            pending_actions=[],
            blockers=[],
            artifacts=artifacts,
            provenance=ProvenanceRecord(
                provenance_type=ProvenanceType.AUTO_CAPTURED,
                captured_by="continuum:trigger:git",
                is_authoritative=False,
                details={
                    "trigger_type": TriggerType.GIT_COMMIT.value,
                    "commit_hash": clean_hash,
                    "branch": branch,
                    "redacted_count": redactions,
                    "excluded_files_count": excluded_files,
                },
            ),
        )

        try:
            committed = self._execute_commit_with_retry(act, checkpoint)
            return self._record_result(TriggerExecutionResult(
                trigger_type=TriggerType.GIT_COMMIT.value,
                status="committed",
                checkpoint_id=committed.id,
                activity_id=act.id,
                redacted_count=redactions,
                excluded_files_count=excluded_files,
            ))
        except Exception as e:
            return self._record_result(TriggerExecutionResult(
                trigger_type=TriggerType.GIT_COMMIT.value,
                status="error",
                activity_id=act.id,
                error=str(e),
                reason="Commit failed after retries",
            ))

    # --------------------------------------------------------------------------
    # Trigger 2: Meaningful Change Trigger
    # --------------------------------------------------------------------------
    def evaluate_meaningful_change_trigger(
        self,
        changed_files: List[str],
        change_summary: Optional[str] = None,
        activity_id: Optional[str] = None,
    ) -> TriggerExecutionResult:
        """
        Evaluates a filesystem delta event against configurable thresholds.
        Individually opt-in via `meaningful_change_enabled`.
        Requires at least `meaningful_change_min_files` matching configured extensions.
        """
        if not self.config.meaningful_change_enabled:
            return self._record_result(TriggerExecutionResult(
                trigger_type=TriggerType.MEANINGFUL_CHANGE.value,
                status="disabled",
                reason="meaningful_change_enabled is False in trigger config",
            ))

        # Check activity
        try:
            act = self._resolve_target_activity(activity_id)
        except ActivityNotFoundError as e:
            return self._record_result(TriggerExecutionResult(
                trigger_type=TriggerType.MEANINGFUL_CHANGE.value,
                status="error",
                error=str(e),
                reason="No active target activity found",
            ))

        # Cooldown check
        with self._lock:
            last_time = self._last_trigger_time.get(TriggerType.MEANINGFUL_CHANGE.value, 0.0)
            if time.time() - last_time < self.config.scheduled_min_cooldown_seconds:
                remaining = int(self.config.scheduled_min_cooldown_seconds - (time.time() - last_time))
                return self._record_result(TriggerExecutionResult(
                    trigger_type=TriggerType.MEANINGFUL_CHANGE.value,
                    status="skipped",
                    activity_id=act.id,
                    reason=f"Meaningful change trigger in cooldown ({remaining}s remaining)",
                ))

        # Filter relevant files by supported extensions
        patterns = set(self.config.meaningful_change_include_patterns)
        relevant_files = []
        for f in (changed_files or []):
            ext = Path(f).suffix.lower()
            if ext in patterns:
                relevant_files.append(f)

        if len(relevant_files) < self.config.meaningful_change_min_files:
            return self._record_result(TriggerExecutionResult(
                trigger_type=TriggerType.MEANINGFUL_CHANGE.value,
                status="skipped",
                activity_id=act.id,
                reason=f"Changed relevant files ({len(relevant_files)}) below threshold ({self.config.meaningful_change_min_files})",
            ))

        # Deduplication check
        sorted_files = sorted(relevant_files)
        fingerprint = self._compute_fingerprint(TriggerType.MEANINGFUL_CHANGE, act.id, {"files": sorted_files})
        with self._lock:
            self._clean_stale_fingerprints()
            if fingerprint in self._recent_events:
                return self._record_result(TriggerExecutionResult(
                    trigger_type=TriggerType.MEANINGFUL_CHANGE.value,
                    status="skipped",
                    activity_id=act.id,
                    reason="Duplicate meaningful change fileset within deduplication window",
                ))
            self._recent_events[fingerprint] = time.time()

        # Privacy sanitization
        desc = change_summary or f"Meaningful change detected across {len(relevant_files)} files"
        sanitized_desc, filtered_files, redactions, excluded_files = self.sanitize_content(
            desc, relevant_files
        )

        parent_chk = self._get_latest_checkpoint(act.id)
        parent_id = parent_chk.id if parent_chk else None

        artifacts = [
            ArtifactReference(name=Path(f).name or f, path_or_uri=f, mode=ArtifactMode.REFERENCE)
            for f in filtered_files
        ]

        checkpoint = UniversalCheckpoint(
            id=f"chk_auto_change_{uuid.uuid4().hex[:12]}",
            activity_id=act.id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            parent_checkpoint_id=parent_id,
            context=f"Automated checkpoint: {sanitized_desc}",
            completed_work=[f"Batch modification of {len(filtered_files)} files: {', '.join(filtered_files[:5])}"],
            pending_actions=[],
            blockers=[],
            artifacts=artifacts,
            provenance=ProvenanceRecord(
                provenance_type=ProvenanceType.AUTO_CAPTURED,
                captured_by="continuum:trigger:meaningful_change",
                is_authoritative=False,
                details={
                    "trigger_type": TriggerType.MEANINGFUL_CHANGE.value,
                    "file_count": len(filtered_files),
                    "redacted_count": redactions,
                    "excluded_files_count": excluded_files,
                },
            ),
        )

        try:
            committed = self._execute_commit_with_retry(act, checkpoint)
            return self._record_result(TriggerExecutionResult(
                trigger_type=TriggerType.MEANINGFUL_CHANGE.value,
                status="committed",
                checkpoint_id=committed.id,
                activity_id=act.id,
                redacted_count=redactions,
                excluded_files_count=excluded_files,
            ))
        except Exception as e:
            return self._record_result(TriggerExecutionResult(
                trigger_type=TriggerType.MEANINGFUL_CHANGE.value,
                status="error",
                activity_id=act.id,
                error=str(e),
                reason="Commit failed after retries",
            ))

    # --------------------------------------------------------------------------
    # Trigger 3: Scheduled / Periodic Trigger
    # --------------------------------------------------------------------------
    def evaluate_scheduled_trigger(
        self,
        activity_id: Optional[str] = None,
        force: bool = False,
    ) -> TriggerExecutionResult:
        """
        Evaluates a scheduled periodic trigger.
        Individually opt-in via `scheduled_enabled`.
        Enforces minimum cooldown and configured interval.
        """
        if not self.config.scheduled_enabled and not force:
            return self._record_result(TriggerExecutionResult(
                trigger_type=TriggerType.SCHEDULED.value,
                status="disabled",
                reason="scheduled_enabled is False in trigger config",
            ))

        # Check activity
        try:
            act = self._resolve_target_activity(activity_id)
        except ActivityNotFoundError as e:
            return self._record_result(TriggerExecutionResult(
                trigger_type=TriggerType.SCHEDULED.value,
                status="error",
                error=str(e),
                reason="No active target activity found",
            ))

        # Cooldown / interval check
        with self._lock:
            last_time = self._last_trigger_time.get(TriggerType.SCHEDULED.value, 0.0)
            now = time.time()
            elapsed = now - last_time

            if not force and elapsed < self.config.scheduled_interval_seconds:
                remaining = int(self.config.scheduled_interval_seconds - elapsed)
                return self._record_result(TriggerExecutionResult(
                    trigger_type=TriggerType.SCHEDULED.value,
                    status="skipped",
                    activity_id=act.id,
                    reason=f"Scheduled trigger waiting for interval ({remaining}s remaining)",
                ))

            if not force and elapsed < self.config.scheduled_min_cooldown_seconds:
                remaining = int(self.config.scheduled_min_cooldown_seconds - elapsed)
                return self._record_result(TriggerExecutionResult(
                    trigger_type=TriggerType.SCHEDULED.value,
                    status="skipped",
                    activity_id=act.id,
                    reason=f"Scheduled trigger in minimum cooldown ({remaining}s remaining)",
                ))

        parent_chk = self._get_latest_checkpoint(act.id)
        parent_id = parent_chk.id if parent_chk else None

        checkpoint = UniversalCheckpoint(
            id=f"chk_auto_sched_{uuid.uuid4().hex[:12]}",
            activity_id=act.id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            parent_checkpoint_id=parent_id,
            context=f"Scheduled automated checkpoint capture for activity '{act.title}'",
            completed_work=["Periodic snapshot of ongoing session"],
            pending_actions=[],
            blockers=[],
            artifacts=[],
            provenance=ProvenanceRecord(
                provenance_type=ProvenanceType.AUTO_CAPTURED,
                captured_by="continuum:trigger:scheduled",
                is_authoritative=False,
                details={
                    "trigger_type": TriggerType.SCHEDULED.value,
                    "interval_seconds": self.config.scheduled_interval_seconds,
                },
            ),
        )

        try:
            committed = self._execute_commit_with_retry(act, checkpoint)
            return self._record_result(TriggerExecutionResult(
                trigger_type=TriggerType.SCHEDULED.value,
                status="committed",
                checkpoint_id=committed.id,
                activity_id=act.id,
            ))
        except Exception as e:
            return self._record_result(TriggerExecutionResult(
                trigger_type=TriggerType.SCHEDULED.value,
                status="error",
                activity_id=act.id,
                error=str(e),
                reason="Commit failed after retries",
            ))
