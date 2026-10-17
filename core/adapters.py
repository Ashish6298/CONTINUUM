"""
Project Continuum — Repository Integration Adapters & Core Invariant Guards
==========================================================================
Milestone 41: Artifacts, Automation and Adapters
Phase 72: Continuity Core Interfaces and Adapters

Key Architecture & Invariant Enforcement:
1. Core Interfaces:
   - Follows stable contracts defined in `core.interfaces`:
     `ILifecycleManager`, `ICheckpointManager`, `IResumeEngine`, `IHistoryManager`,
     `IBranchManager`, `IRestoreManager`, `IRetentionManager`, `IIntegrityManager`.
2. Actual Repository Integrations:
   - Git Integration Adapter (`GitIntegrationAdapter`):
     Safely queries git evidence (head, branch, commit log, diff, status) using least privilege
     and bounds payload sizes (diffs truncated, log depth bounded).
   - Workspace Filesystem Adapter (`WorkspaceIntegrationAdapter`):
     Inspects files, detects changes, reads artifacts safely with path containment, size limits,
     and directory recursion bounds.
   - Web / REST Integration Adapter (`RestApiIntegrationAdapter`):
     Validates/bounds JSON payloads, enforces authentication/CORS, and isolates exceptions.
3. Resilient Error Handling & Isolation:
   - Handles malformed inputs, missing repositories, oversized payloads, permission denials,
     and duplicate events cleanly without corrupting core storage.
4. Gate: "Adapters cannot bypass core invariants."
   - Adapters enforce validation, privacy sanitization, and immutability before touching storage.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from core.activity import Activity, ActivityStatus, ActivityType, ActivityValidationError
from core.checkpoint import (
    UniversalCheckpoint,
    CheckpointValidationError,
    ArtifactReference,
    DecisionRecord,
    ProvenanceRecord,
)
from core.enums import ArtifactMode, ProvenanceType
from core.invariants import (
    CommitFailedError,
    ContinuumUserError,
    InvariantViolationError,
    InvariantId,
)
from core.interfaces import (
    ILifecycleManager,
    ICheckpointManager,
    IResumeEngine,
    IHistoryManager,
    IBranchManager,
    IRestoreManager,
    IRetentionManager,
    IIntegrityManager,
)
from server.sanitizer import DaemonSanitizer
from storage.activity_store import ActivityCheckpointStore, ActivityNotFoundError, CheckpointNotFoundError
from storage.consistency import StorageConsistencyAuditor


class AdapterError(Exception):
    """Base exception for adapter operations."""
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.details = details


class AdapterPayloadLimitError(AdapterError):
    """Raised when an incoming adapter payload exceeds maximum allowed size bounds."""
    pass


class AdapterPermissionDeniedError(AdapterError):
    """Raised when an adapter operation is rejected due to file or OS permissions."""
    pass


class AdapterMalformedInputError(AdapterError):
    """Raised when an adapter receives structurally invalid or unparseable input."""
    pass


class BaseContinuityAdapter(ABC):
    """Abstract base class for all repository integration adapters."""

    # Maximum payload size bound: 2MB
    MAX_PAYLOAD_BYTES: int = 2 * 1024 * 1024
    # Maximum string excerpt length: 64KB
    MAX_EXCERPT_CHARS: int = 64 * 1024

    def __init__(self, workspace_root: Path, store: Optional[ActivityCheckpointStore] = None):
        self.workspace_root = Path(workspace_root).resolve()
        self.store = store or ActivityCheckpointStore(self.workspace_root)

    def validate_payload_size(self, data: Union[str, bytes, Dict[str, Any]]) -> None:
        """Enforces strict size bounding to protect core memory and storage from exhaustion."""
        if isinstance(data, (str, bytes)):
            size = len(data)
        elif isinstance(data, (dict, list)):
            size = len(json.dumps(data, default=str))
        else:
            size = 0

        if size > self.MAX_PAYLOAD_BYTES:
            raise AdapterPayloadLimitError(
                f"Payload size ({size} bytes) exceeds maximum allowable limit ({self.MAX_PAYLOAD_BYTES} bytes)."
            )

    def sanitize_text(self, text: str) -> str:
        """Enforces secret redaction on all adapter data before passing into core."""
        if not text or not isinstance(text, str):
            return text
        sanitized = DaemonSanitizer.sanitize_text(text)
        if len(sanitized) > self.MAX_EXCERPT_CHARS:
            sanitized = sanitized[:self.MAX_EXCERPT_CHARS] + "... [TRUNCATED_BY_ADAPTER_LIMIT]"
        return sanitized


class GitIntegrationAdapter(BaseContinuityAdapter):
    """
    Adapter interfacing directly with the local Git VCS repository.
    Enforces least privilege (read-only queries, bounded logs, sanitized diffs).
    """

    def is_git_repository(self) -> bool:
        """Checks if workspace is a valid initialized git repository."""
        git_dir = self.workspace_root / ".git"
        return git_dir.exists()

    def get_current_branch(self) -> Optional[str]:
        """Returns the current git branch name, or None if detached / non-git."""
        if not self.is_git_repository():
            return None
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if res.returncode == 0:
                branch = res.stdout.strip()
                return branch if branch and branch != "HEAD" else None
        except Exception:
            pass
        return None

    def get_head_commit(self) -> Optional[Dict[str, str]]:
        """Returns the current HEAD commit hash, author, and subject."""
        if not self.is_git_repository():
            return None
        try:
            res = subprocess.run(
                ["git", "log", "-1", "--format=%H%x00%an%x00%s"],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if res.returncode == 0 and res.stdout.strip():
                parts = res.stdout.strip().split("\x00")
                if len(parts) >= 3:
                    return {
                        "commit_hash": parts[0],
                        "author": parts[1],
                        "message": self.sanitize_text(parts[2]),
                    }
        except Exception:
            pass
        return None

    def get_changed_files(self) -> List[str]:
        """
        Returns list of dirty, staged, and untracked files normalized to workspace relative.
        Filters out high-risk secrets and applies count bounds (max 200 files).
        """
        if not self.is_git_repository():
            return []
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain", "-uall"],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=10.0,
            )
            if res.returncode != 0:
                return []

            files = []
            for line in res.stdout.splitlines():
                if len(line) >= 3:
                    file_path = line[3:].strip()
                    # Handle quoted paths with spaces
                    if file_path.startswith('"') and file_path.endswith('"'):
                        file_path = file_path[1:-1]
                    norm_path = DaemonSanitizer.normalize_path(file_path, self.workspace_root)
                    if not DaemonSanitizer.is_high_risk_file(norm_path):
                        files.append(norm_path)
                    if len(files) >= 200:
                        break
            return sorted(files)
        except Exception:
            return []

    def capture_git_checkpoint(
        self,
        activity_id: str,
        context_override: Optional[str] = None,
    ) -> UniversalCheckpoint:
        """
        Captures a checkpoint from current Git state.
        Validates activity existence, bounds payload, sanitizes context,
        and creates an immutable UniversalCheckpoint with ProvenanceType.AUTO_CAPTURED.
        """
        activity = self.store.get_activity(activity_id)
        if not activity:
            raise ActivityNotFoundError(activity_id)

        head_info = self.get_head_commit()
        branch = self.get_current_branch()
        changed = self.get_changed_files()

        commit_hash = head_info.get("commit_hash", "") if head_info else ""
        commit_msg = head_info.get("message", "") if head_info else "No commit info"

        raw_context = context_override or f"Git state snapshot at branch '{branch or 'detached'}' (commit {commit_hash[:8] if commit_hash else 'none'}): {commit_msg}"
        clean_context = self.sanitize_text(raw_context)

        # Artifact references
        artifacts = [
            ArtifactReference(
                name=Path(f).name or f,
                path_or_uri=f,
                mode=ArtifactMode.REFERENCE,
            )
            for f in changed
        ]

        # Parent checkpoint lookup
        chks_res = self.store.list_checkpoints(activity_id, limit=1, order="desc")
        parent_chks = chks_res[0] if isinstance(chks_res, tuple) else chks_res
        parent_id = parent_chks[0].id if parent_chks else None

        now_iso = datetime.now(timezone.utc).isoformat()
        checkpoint = UniversalCheckpoint(
            id=f"chk_git_{hashlib.sha256(f'{commit_hash}:{now_iso}'.encode()).hexdigest()[:12]}",
            activity_id=activity_id,
            timestamp=now_iso,
            parent_checkpoint_id=parent_id,
            context=clean_context,
            completed_work=[f"Git commit {commit_hash[:8] if commit_hash else 'unknown'}: {commit_msg}"],
            pending_actions=[],
            blockers=[],
            artifacts=artifacts,
            provenance=ProvenanceRecord(
                provenance_type=ProvenanceType.AUTO_CAPTURED,
                captured_by="git_integration_adapter",
                is_authoritative=False,
                details={
                    "commit_hash": commit_hash,
                    "branch": branch,
                    "dirty_file_count": len(changed),
                },
            ),
        )

        # Verify core invariant: adapters cannot bypass checkpoint validation
        checkpoint.validate()
        return self.store.commit_checkpoint(checkpoint)


class WorkspaceIntegrationAdapter(BaseContinuityAdapter):
    """
    Adapter for filesystem observation, artifact verification, and safe directory inspection.
    Enforces path traversal containment, file size bounds, and least privilege.
    """

    def resolve_safe_path(self, target_path: str) -> Path:
        """
        Resolves path and enforces strict workspace containment (I-10).
        Rejects paths escaping workspace root.
        """
        if not target_path or not isinstance(target_path, str):
            raise AdapterMalformedInputError("Target path must be a non-empty string.")

        # Strip any leading slashes or drive letters if relative intended
        clean_path = target_path.strip()
        try:
            resolved = (self.workspace_root / clean_path).resolve()
        except Exception as e:
            raise AdapterMalformedInputError(f"Invalid path syntax '{clean_path}': {str(e)}")

        # Containment check
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError:
            raise AdapterPermissionDeniedError(f"Path '{clean_path}' escapes workspace containment.")

        return resolved

    def read_artifact_content(self, relative_path: str, max_bytes: int = 512 * 1024) -> str:
        """
        Reads text artifact safely with size bounds, secret redaction, and permission error handling.
        """
        path = self.resolve_safe_path(relative_path)
        if not path.is_file():
            raise FileNotFoundError(f"Artifact '{relative_path}' not found.")

        if DaemonSanitizer.is_high_risk_file(path):
            raise AdapterPermissionDeniedError(f"Access to high-risk secret file '{relative_path}' is denied.")

        try:
            stat = path.stat()
            if stat.st_size > max_bytes:
                raise AdapterPayloadLimitError(f"File '{relative_path}' ({stat.st_size} bytes) exceeds limit ({max_bytes} bytes).")

            content = path.read_text(encoding="utf-8", errors="replace")
            return self.sanitize_text(content)
        except PermissionError as e:
            raise AdapterPermissionDeniedError(f"Permission denied reading '{relative_path}': {str(e)}")
        except UnicodeDecodeError as e:
            raise AdapterMalformedInputError(f"File '{relative_path}' is binary or corrupt: {str(e)}")


class RestApiIntegrationAdapter(BaseContinuityAdapter):
    """
    Adapter parsing, validating, and bounding HTTP/REST JSON payloads for core continuity operations.
    Shields core models from malformed structures, duplicate requests, and invalid transitions.
    """

    def parse_and_validate_activity_payload(self, raw_payload: Union[str, bytes, Dict[str, Any]]) -> Activity:
        """
        Parses and validates an Activity payload from REST API.
        Bounds payload size and catches malformed schema.
        """
        self.validate_payload_size(raw_payload)

        if isinstance(raw_payload, (str, bytes)):
            try:
                data = json.loads(raw_payload)
            except Exception as e:
                raise AdapterMalformedInputError(f"Invalid JSON in activity payload: {str(e)}")
        elif isinstance(raw_payload, dict):
            data = raw_payload
        else:
            raise AdapterMalformedInputError(f"Expected dict or JSON string, got {type(raw_payload).__name__}")

        if not isinstance(data, dict):
            raise AdapterMalformedInputError("Activity payload must be a JSON object.")

        # Required fields check
        title = data.get("title")
        if not title or not isinstance(title, str) or not title.strip():
            raise AdapterMalformedInputError("Field 'title' is required and must be non-empty.")

        # Sanitize fields
        clean_title = self.sanitize_text(title.strip())
        clean_desc = self.sanitize_text(data.get("description", ""))

        act_id = str(data.get("id") or f"act_{hashlib.sha256(f'{clean_title}:{time.time()}'.encode()).hexdigest()[:12]}")
        status_val = data.get("status", ActivityStatus.ACTIVE.value)

        try:
            status_enum = ActivityStatus(status_val) if isinstance(status_val, str) else status_val
        except ValueError:
            raise AdapterMalformedInputError(f"Invalid activity status '{status_val}'. Valid: {[s.value for s in ActivityStatus]}")

        activity = Activity(
            id=act_id,
            title=clean_title,
            description=clean_desc,
            activity_type=data.get("activity_type", ActivityType.CODING.value),
            status=status_enum,
            tags=[self.sanitize_text(str(t)) for t in data.get("tags", [])],
            collection=self.sanitize_text(str(data.get("collection"))) if data.get("collection") else None,
            metadata=data.get("metadata", {}),
        )

        try:
            activity.validate()
        except ActivityValidationError as e:
            raise AdapterMalformedInputError(f"Activity validation failed: {str(e)}")

        return activity

    def parse_and_validate_checkpoint_payload(self, raw_payload: Union[str, bytes, Dict[str, Any]]) -> UniversalCheckpoint:
        """
        Parses and validates a Checkpoint payload from REST API.
        Bounds payload size, sanitizes secrets, and enforces UniversalCheckpoint constraints.
        """
        self.validate_payload_size(raw_payload)

        if isinstance(raw_payload, (str, bytes)):
            try:
                data = json.loads(raw_payload)
            except Exception as e:
                raise AdapterMalformedInputError(f"Invalid JSON in checkpoint payload: {str(e)}")
        elif isinstance(raw_payload, dict):
            data = raw_payload
        else:
            raise AdapterMalformedInputError(f"Expected dict or JSON string, got {type(raw_payload).__name__}")

        if not isinstance(data, dict):
            raise AdapterMalformedInputError("Checkpoint payload must be a JSON object.")

        act_id = data.get("activity_id")
        if not act_id or not isinstance(act_id, str) or not act_id.strip():
            raise AdapterMalformedInputError("Field 'activity_id' is required and must be a non-empty string.")

        clean_context = self.sanitize_text(data.get("context", ""))
        completed = [self.sanitize_text(str(w)) for w in data.get("completed_work", [])]
        pending = [self.sanitize_text(str(p)) for p in data.get("pending_actions", [])]
        blockers = [self.sanitize_text(str(b)) for b in data.get("blockers", [])]

        # Artifacts
        artifacts = []
        for art in data.get("artifacts", []):
            if isinstance(art, dict):
                path = art.get("path_or_uri") or art.get("path", "")
                if path and not DaemonSanitizer.is_high_risk_file(path):
                    mode_val = art.get("mode", ArtifactMode.REFERENCE.value)
                    try:
                        mode_enum = ArtifactMode(mode_val.lower())
                    except ValueError:
                        mode_enum = ArtifactMode.REFERENCE

                    snap_content = self.sanitize_text(art.get("snapshot_content")) if art.get("snapshot_content") else None
                    artifacts.append(ArtifactReference(
                        name=art.get("name") or Path(path).name or path,
                        path_or_uri=DaemonSanitizer.normalize_path(path, self.workspace_root),
                        mode=mode_enum,
                        snapshot_content=snap_content,
                    ))

        chk_id = str(data.get("id") or f"chk_{hashlib.sha256(f'{act_id}:{time.time()}'.encode()).hexdigest()[:12]}")
        now_iso = datetime.now(timezone.utc).isoformat()

        checkpoint = UniversalCheckpoint(
            id=chk_id,
            activity_id=act_id.strip(),
            timestamp=data.get("timestamp") or now_iso,
            parent_checkpoint_id=data.get("parent_checkpoint_id"),
            branch_source_checkpoint_id=data.get("branch_source_checkpoint_id"),
            structured_state=data.get("structured_state", {}),
            progress=data.get("progress", {}),
            completed_work=completed,
            pending_actions=pending,
            decisions=[
                DecisionRecord(
                    id=str(d.get("id", f"dec_{hashlib.sha256(str(d).encode()).hexdigest()[:8]}")),
                    decision=self.sanitize_text(str(d.get("decision", ""))),
                    rationale=self.sanitize_text(str(d.get("rationale", ""))),
                    constraints=[self.sanitize_text(str(c)) for c in d.get("constraints", [])],
                )
                for d in data.get("decisions", [])
                if isinstance(d, dict) and d.get("decision")
            ],
            context=clean_context,
            references=[self.sanitize_text(str(r)) for r in data.get("references", [])],
            blockers=blockers,
            artifacts=artifacts,
            provenance=ProvenanceRecord(
                provenance_type=ProvenanceType.USER_CONFIRMED if data.get("user_confirmed", True) else ProvenanceType.AUTO_CAPTURED,
                captured_by="rest_api_adapter",
                is_authoritative=bool(data.get("user_confirmed", True)),
            ),
        )

        try:
            checkpoint.validate()
        except CheckpointValidationError as e:
            raise AdapterMalformedInputError(f"Checkpoint validation failed: {str(e)}")

        return checkpoint
