"""
Project Continuum — Manual Checkpoint Capture Engine & Privacy Sanitization
==========================================================================
Milestone 38: Capture and Resume
Phase 59: Manual Checkpoint Capture

Implements:
1. `ManualCaptureRequest` and `ManualCaptureResponse` DTOs.
2. `ManualCaptureEngine`:
   - Validates input activity and checkpoint fields.
   - Enforces privacy exclusions per settings (redacts secrets from context, notes, decisions, artifacts).
   - Accurately checks for and rejects duplicate submissions via idempotency keys and state hashing.
   - Creates authoritative `UniversalCheckpoint` with `ProvenanceType.USER_CONFIRMED`.
   - Durable, atomic commit to `ActivityCheckpointStore`.
   - Independent of automation / AI settings (Gate: manual capture works offline with no AI).
   - Returns clear commit success/failure details.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from core.activity import Activity, ActivityStatus, ActivityType
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


class DuplicateSubmissionError(ValueError):
    """Raised when an identical manual checkpoint submission is detected within the dedup window."""
    def __init__(self, message: str, idempotency_key: Optional[str] = None):
        super().__init__(message)
        self.idempotency_key = idempotency_key


class CaptureStorageError(RuntimeError):
    """Raised when persistent storage fails during manual checkpoint commit."""
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.original_error = original_error


@dataclass
class PrivacySettings:
    """Configures privacy exclusions and secret redaction for manual checkpoint capture."""
    redact_secrets: bool = True
    exclude_high_risk_files: bool = True
    custom_denied_terms: List[str] = field(default_factory=list)
    mask_file_paths: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "redact_secrets": self.redact_secrets,
            "exclude_high_risk_files": self.exclude_high_risk_files,
            "custom_denied_terms": list(self.custom_denied_terms),
            "mask_file_paths": self.mask_file_paths,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "PrivacySettings":
        if not data:
            return cls()
        return cls(
            redact_secrets=bool(data.get("redact_secrets", True)),
            exclude_high_risk_files=bool(data.get("exclude_high_risk_files", True)),
            custom_denied_terms=list(data.get("custom_denied_terms", [])),
            mask_file_paths=bool(data.get("mask_file_paths", False)),
        )


@dataclass
class ManualCaptureRequest:
    """
    Payload for manual checkpoint capture.
    Allows full or partial valid checkpoints; all fields except activity_id are optional.
    """
    activity_id: str
    checkpoint_id: Optional[str] = None
    parent_checkpoint_id: Optional[str] = None
    structured_state: Dict[str, Any] = field(default_factory=dict)
    progress: Dict[str, Any] = field(default_factory=dict)
    completed_work: List[str] = field(default_factory=list)
    pending_actions: List[str] = field(default_factory=list)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    context: str = ""
    references: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    permitted_excerpts: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    idempotency_key: Optional[str] = None
    user_identifier: str = "user"
    privacy_settings: PrivacySettings = field(default_factory=PrivacySettings)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "checkpoint_id": self.checkpoint_id,
            "parent_checkpoint_id": self.parent_checkpoint_id,
            "structured_state": dict(self.structured_state),
            "progress": dict(self.progress),
            "completed_work": list(self.completed_work),
            "pending_actions": list(self.pending_actions),
            "decisions": list(self.decisions),
            "context": self.context,
            "references": list(self.references),
            "blockers": list(self.blockers),
            "artifacts": list(self.artifacts),
            "permitted_excerpts": list(self.permitted_excerpts),
            "metadata": dict(self.metadata),
            "idempotency_key": self.idempotency_key,
            "user_identifier": self.user_identifier,
            "privacy_settings": self.privacy_settings.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ManualCaptureRequest":
        if not isinstance(data, dict):
            raise CheckpointValidationError("ManualCaptureRequest payload must be a JSON dictionary.")
        act_id = data.get("activity_id")
        if not act_id or not isinstance(act_id, str) or not act_id.strip():
            raise CheckpointValidationError("Field 'activity_id' is required and must be a non-empty string.")

        priv_data = data.get("privacy_settings")
        privacy = PrivacySettings.from_dict(priv_data) if isinstance(priv_data, dict) else PrivacySettings()

        return cls(
            activity_id=act_id.strip(),
            checkpoint_id=data.get("checkpoint_id"),
            parent_checkpoint_id=data.get("parent_checkpoint_id"),
            structured_state=data.get("structured_state") if isinstance(data.get("structured_state"), dict) else {},
            progress=data.get("progress") if isinstance(data.get("progress"), dict) else {},
            completed_work=list(data.get("completed_work") or []),
            pending_actions=list(data.get("pending_actions") or []),
            decisions=list(data.get("decisions") or []),
            context=str(data.get("context") or ""),
            references=list(data.get("references") or []),
            blockers=list(data.get("blockers") or []),
            artifacts=list(data.get("artifacts") or []),
            permitted_excerpts=list(data.get("permitted_excerpts") or []),
            metadata=dict(data.get("metadata") or {}),
            idempotency_key=data.get("idempotency_key"),
            user_identifier=str(data.get("user_identifier") or "user"),
            privacy_settings=privacy,
        )


@dataclass
class ManualCaptureResponse:
    """Result of manual checkpoint capture operation."""
    success: bool
    checkpoint: Optional[Dict[str, Any]] = None
    checkpoint_id: Optional[str] = None
    activity_id: Optional[str] = None
    error: Optional[str] = None
    redacted_count: int = 0
    excluded_artifacts_count: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "checkpoint": self.checkpoint,
            "checkpoint_id": self.checkpoint_id,
            "activity_id": self.activity_id,
            "error": self.error,
            "redacted_count": self.redacted_count,
            "excluded_artifacts_count": self.excluded_artifacts_count,
            "timestamp": self.timestamp,
        }


class ManualCaptureEngine:
    """
    Engine executing manual checkpoint capture workflows.
    Ensures:
    1. Validation of partial and full checkpoints.
    2. Exclusion of sensitive tokens, secrets, and high-risk paths per privacy settings.
    3. Idempotency and double-submission defense using keys and content hashes.
    4. Authoritative persistence with explicit success/failure reporting.
    5. Clean separation from any background automation or AI flags.
    """

    # In-memory deduplication window: prevents double-clicks / rapid duplicate submits
    DEDUP_WINDOW_SECONDS = 30.0

    def __init__(self, store: ActivityCheckpointStore, workspace_root: Optional[Path] = None):
        self.store = store
        self.workspace_root = (workspace_root or store.workspace_root).resolve()
        self._recent_submissions: Dict[str, float] = {}  # hash -> timestamp
        self._lock = threading.Lock()

    def _clean_stale_dedup_cache(self) -> None:
        """Removes entries older than DEDUP_WINDOW_SECONDS."""
        now = time.time()
        stale_keys = [k for k, t in self._recent_submissions.items() if now - t > self.DEDUP_WINDOW_SECONDS]
        for k in stale_keys:
            self._recent_submissions.pop(k, None)

    def _compute_submission_hash(self, req: ManualCaptureRequest) -> str:
        """Computes a deterministic hash of request intent to detect accidental duplicate submits."""
        if req.idempotency_key:
            return f"key:{req.idempotency_key.strip()}"

        data_rep = {
            "act": req.activity_id,
            "ctx": req.context.strip(),
            "comp": sorted(req.completed_work),
            "pend": sorted(req.pending_actions),
            "bloc": sorted(req.blockers),
            "parent": req.parent_checkpoint_id,
        }
        encoded = json.dumps(data_rep, sort_keys=True).encode("utf-8")
        return f"hash:{hashlib.sha256(encoded).hexdigest()}"

    def sanitize_text(self, text: str, settings: PrivacySettings) -> Tuple[str, int]:
        """
        Redacts known secret patterns and custom denied terms from a string.
        Returns (sanitized_string, redactions_performed_count).
        """
        if not text or not settings.redact_secrets:
            return text, 0

        redactions = 0
        result = text

        # 1. Regex secret patterns from DaemonSanitizer
        for pattern, replacement in DaemonSanitizer.INLINE_SECRET_PATTERNS:
            matches = list(pattern.finditer(result))
            if matches:
                redactions += len(matches)
                result = pattern.sub(replacement, result)

        # 2. Custom denied terms
        for term in settings.custom_denied_terms:
            if term and term.strip():
                clean_term = term.strip()
                escaped = re.escape(clean_term)
                pattern = re.compile(escaped, re.IGNORECASE)
                matches = list(pattern.finditer(result))
                if matches:
                    redactions += len(matches)
                    result = pattern.sub("<REDACTED_SENSITIVE>", result)

        return result, redactions

    def capture_checkpoint(self, request: ManualCaptureRequest) -> ManualCaptureResponse:
        """
        Executes manual checkpoint capture.
        Validates, sanitizes, guards against duplicate submissions, and durably persists.
        """
        # 1. Guard against duplicate submission
        sub_hash = self._compute_submission_hash(request)
        with self._lock:
            self._clean_stale_dedup_cache()
            if sub_hash in self._recent_submissions:
                raise DuplicateSubmissionError(
                    f"Duplicate checkpoint submission detected. Please wait before re-submitting.",
                    idempotency_key=request.idempotency_key,
                )
            self._recent_submissions[sub_hash] = time.time()

        # 2. Verify parent activity exists
        try:
            activity = self.store.get_activity(request.activity_id)
        except ActivityNotFoundError:
            raise ActivityNotFoundError(request.activity_id)
        except Exception as e:
            raise CaptureStorageError(f"Storage error verifying activity: {e}", original_error=e)

        # 3. Apply privacy sanitization and exclusions
        total_redactions = 0

        # Sanitize context
        sanitized_context, c_red = self.sanitize_text(request.context, request.privacy_settings)
        total_redactions += c_red

        # Sanitize completed work
        sanitized_completed = []
        for w in request.completed_work:
            s_w, r_cnt = self.sanitize_text(str(w), request.privacy_settings)
            total_redactions += r_cnt
            sanitized_completed.append(s_w)

        # Sanitize pending actions
        sanitized_pending = []
        for a in request.pending_actions:
            s_a, r_cnt = self.sanitize_text(str(a), request.privacy_settings)
            total_redactions += r_cnt
            sanitized_pending.append(s_a)

        # Sanitize blockers
        sanitized_blockers = []
        for b in request.blockers:
            s_b, r_cnt = self.sanitize_text(str(b), request.privacy_settings)
            total_redactions += r_cnt
            sanitized_blockers.append(s_b)

        # Sanitize decisions
        sanitized_decisions: List[DecisionRecord] = []
        for d in request.decisions:
            if not isinstance(d, dict):
                continue
            raw_dec = str(d.get("decision", ""))
            raw_rat = str(d.get("rationale", ""))
            s_dec, r1 = self.sanitize_text(raw_dec, request.privacy_settings)
            s_rat, r2 = self.sanitize_text(raw_rat, request.privacy_settings)
            total_redactions += (r1 + r2)

            sanitized_constraints = []
            for c in d.get("constraints", []):
                s_c, r3 = self.sanitize_text(str(c), request.privacy_settings)
                total_redactions += r3
                sanitized_constraints.append(s_c)

            sanitized_decisions.append(
                DecisionRecord(
                    id=str(d.get("id") or f"dec_{uuid.uuid4().hex[:8]}"),
                    decision=s_dec,
                    rationale=s_rat,
                    constraints=sanitized_constraints,
                    recorded_at=str(d.get("recorded_at") or datetime.now(timezone.utc).isoformat()),
                )
            )

        # Phase 70: Filter, sanitize, and validate artifacts via ArtifactManager
        from core.artifact_manager import ArtifactManager

        sanitized_artifacts: List[ArtifactReference] = []
        excluded_artifacts_count = 0
        total_snapshot_bytes = 0

        for art in request.artifacts:
            if not isinstance(art, dict):
                continue
            raw_path = str(art.get("path_or_uri") or "")
            name = str(art.get("name") or Path(raw_path).name or raw_path or "unnamed_artifact")

            # Privacy rule: Exclude high-risk credential files (.env, *.pem, *.key, etc.)
            if request.privacy_settings.exclude_high_risk_files and DaemonSanitizer.is_high_risk_file(raw_path):
                excluded_artifacts_count += 1
                continue

            norm_path = ArtifactManager.normalize_path(raw_path, self.workspace_root)
            mode_str = str(art.get("mode") or ArtifactMode.REFERENCE.value).lower()
            try:
                mode_enum = ArtifactMode(mode_str)
            except (ValueError, AttributeError):
                mode_enum = ArtifactMode.REFERENCE

            captured_ts = str(art.get("captured_at") or datetime.now(timezone.utc).isoformat())

            if mode_enum == ArtifactMode.SNAPSHOT:
                inspection = ArtifactManager.inspect_resource(norm_path, self.workspace_root)
                if inspection.get("is_directory"):
                    # Directories can NEVER be snapshot-copied (Phase 70 guard)
                    mode_enum = ArtifactMode.REFERENCE
                    snapshot_content = None
                    storage_visibility = "workspace_local"
                elif inspection.get("is_high_risk"):
                    excluded_artifacts_count += 1
                    continue
                else:
                    raw_snap = art.get("snapshot_content")
                    if raw_snap is None and inspection["exists"]:
                        local_p = ArtifactManager.resolve_local_path(norm_path, self.workspace_root)
                        try:
                            raw_snap = local_p.read_text(encoding="utf-8")
                        except Exception:
                            raw_snap = None

                    if raw_snap is not None:
                        if request.privacy_settings.redact_secrets:
                            raw_snap, r_art = self.sanitize_text(str(raw_snap), request.privacy_settings)
                            total_redactions += r_art

                        snap_bytes = len(raw_snap.encode("utf-8"))
                        if (snap_bytes <= ArtifactManager.MAX_SNAPSHOT_FILE_BYTES and
                                (total_snapshot_bytes + snap_bytes) <= ArtifactManager.MAX_TOTAL_SNAPSHOT_BYTES):
                            snapshot_content = raw_snap
                            storage_visibility = "embedded_snapshot"
                            total_snapshot_bytes += snap_bytes
                        else:
                            # Size limit reached - downgrade to reference
                            mode_enum = ArtifactMode.REFERENCE
                            snapshot_content = None
                            storage_visibility = "workspace_local"
                    else:
                        mode_enum = ArtifactMode.REFERENCE
                        snapshot_content = None
                        storage_visibility = inspection["storage_visibility"]
            else:
                # Default: REFERENCE
                mode_enum = ArtifactMode.REFERENCE
                snapshot_content = None
                inspection = ArtifactManager.inspect_resource(norm_path, self.workspace_root)
                storage_visibility = inspection["storage_visibility"]

            insp = ArtifactManager.inspect_resource(norm_path, self.workspace_root)
            checksum = art.get("checksum_sha256") or insp.get("checksum_sha256")
            size_b = len(snapshot_content.encode("utf-8")) if snapshot_content is not None else (art.get("size_bytes") or insp.get("size_bytes"))

            sanitized_artifacts.append(
                ArtifactReference(
                    name=name,
                    path_or_uri=norm_path,
                    mode=mode_enum,
                    captured_at=captured_ts,
                    checksum_sha256=checksum,
                    size_bytes=size_b,
                    snapshot_content=snapshot_content,
                    storage_visibility=storage_visibility,
                    is_present=insp.get("exists", False),
                    metadata=dict(art.get("metadata", {}))
                )
            )

        # 4. Construct authoritative UniversalCheckpoint with Provenance
        chk_id = request.checkpoint_id or f"chk_{uuid.uuid4().hex[:12]}"
        provenance = ProvenanceRecord(
            provenance_type=ProvenanceType.USER_CONFIRMED,
            captured_by=request.user_identifier,
            captured_at=datetime.now(timezone.utc).isoformat(),
            is_authoritative=True,
            details={"capture_method": "manual_ui", "idempotency_key": request.idempotency_key},
        )

        checkpoint = UniversalCheckpoint(
            id=chk_id,
            activity_id=request.activity_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            parent_checkpoint_id=request.parent_checkpoint_id,
            branch_source_checkpoint_id=None,
            structured_state=dict(request.structured_state),
            progress=dict(request.progress),
            completed_work=sanitized_completed,
            pending_actions=sanitized_pending,
            decisions=sanitized_decisions,
            context=sanitized_context,
            references=list(request.references),
            blockers=sanitized_blockers,
            artifacts=sanitized_artifacts,
            permitted_excerpts=list(request.permitted_excerpts),
            provenance=provenance,
            resume_brief=None,  # ResumeBrief generated separately in Phase 60
            metadata=dict(request.metadata),
        )

        # 5. Persist to ActivityCheckpointStore with durable commit confirmation (I-02)
        try:
            saved_checkpoint = self.store.commit_checkpoint(checkpoint)
        except DanglingReferenceError as e:
            raise DanglingReferenceError(str(e), reference_id=request.parent_checkpoint_id or "")
        except CommitFailedError as e:
            raise CaptureStorageError(f"Commit failed to store checkpoint: {e}", original_error=e)
        except Exception as e:
            raise CaptureStorageError(f"Unexpected storage error persisting checkpoint: {e}", original_error=e)

        return ManualCaptureResponse(
            success=True,
            checkpoint=saved_checkpoint.to_dict(),
            checkpoint_id=saved_checkpoint.id,
            activity_id=saved_checkpoint.activity_id,
            redacted_count=total_redactions,
            excluded_artifacts_count=excluded_artifacts_count,
            timestamp=saved_checkpoint.timestamp,
        )
