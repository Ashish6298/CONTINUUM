"""
Project Continuum - Checkpoint & Provenance Domain Model (v1.4.0)
================================================================
Milestone 36 - Phase 54: Checkpoint and Provenance Model.
Defines the Universal Checkpoint entity, structured state, progress metrics,
completed work, pending actions, decisions & rationale, context, references,
blockers, artifacts (references vs snapshots), excerpts, provenance classifications,
and derived Resume Briefs.

Invariants:
- I-01: Stable checkpoint identity across edits and migrations.
- I-06: Briefs are derived, not authoritative. Authoritative state takes precedence.
- I-18: Backward compatibility: optional fields remain optional; legacy records
  remain fully readable.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import uuid

from core.enums import ArtifactMode, ProvenanceType


class CheckpointValidationError(ValueError):
    """Raised when a Checkpoint or its child entities violate structural contracts."""
    pass


@dataclass
class ProvenanceRecord:
    """
    Tracks origin and confirmation status of checkpoint data.
    Distinguishes user-confirmed facts from imported, auto-captured, and AI-generated data.
    """
    provenance_type: ProvenanceType = ProvenanceType.USER_CONFIRMED
    captured_by: str = "user"
    captured_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_authoritative: bool = True
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provenance_type": self.provenance_type.value if isinstance(self.provenance_type, ProvenanceType) else str(self.provenance_type),
            "captured_by": self.captured_by,
            "captured_at": self.captured_at,
            "is_authoritative": self.is_authoritative,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProvenanceRecord":
        pt = data.get("provenance_type", ProvenanceType.USER_CONFIRMED.value)
        try:
            pt_enum = ProvenanceType(pt.lower())
        except (ValueError, AttributeError):
            pt_enum = ProvenanceType.USER_CONFIRMED

        return cls(
            provenance_type=pt_enum,
            captured_by=data.get("captured_by", "user"),
            captured_at=data.get("captured_at", datetime.now(timezone.utc).isoformat()),
            is_authoritative=bool(data.get("is_authoritative", True)),
            details=data.get("details", {}),
        )


@dataclass
class DecisionRecord:
    """
    Represents an explicit design decision, choice rationale, and associated constraints.
    """
    id: str
    decision: str
    rationale: str = ""
    constraints: List[str] = field(default_factory=list)
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "decision": self.decision,
            "rationale": self.rationale,
            "constraints": list(self.constraints),
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecisionRecord":
        return cls(
            id=data.get("id", f"dec_{uuid.uuid4().hex[:8]}"),
            decision=data["decision"],
            rationale=data.get("rationale", ""),
            constraints=data.get("constraints", []),
            recorded_at=data.get("recorded_at", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class ArtifactReference:
    """
    Represents an artifact linked to a checkpoint.
    Phase 70: References by default; optional user-selected snapshot copies.
    Labels live reference vs snapshot with capture timestamp and storage visibility.
    """
    name: str
    path_or_uri: str
    mode: ArtifactMode = ArtifactMode.REFERENCE
    captured_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    checksum_sha256: Optional[str] = None
    size_bytes: Optional[int] = None
    snapshot_content: Optional[str] = None
    storage_visibility: str = "workspace_local"  # "workspace_local", "external_uri", "embedded_snapshot", "missing"
    is_present: Optional[bool] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_snapshot(self) -> bool:
        mode_val = self.mode.value if isinstance(self.mode, ArtifactMode) else str(self.mode)
        return mode_val.lower() == ArtifactMode.SNAPSHOT.value

    @property
    def is_reference(self) -> bool:
        mode_val = self.mode.value if isinstance(self.mode, ArtifactMode) else str(self.mode)
        return mode_val.lower() == ArtifactMode.REFERENCE.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path_or_uri": self.path_or_uri,
            "mode": self.mode.value if isinstance(self.mode, ArtifactMode) else str(self.mode),
            "captured_at": self.captured_at,
            "checksum_sha256": self.checksum_sha256,
            "size_bytes": self.size_bytes,
            "snapshot_content": self.snapshot_content,
            "storage_visibility": self.storage_visibility,
            "is_present": self.is_present,
            "metadata": dict(self.metadata) if self.metadata else {},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArtifactReference":
        mode_val = data.get("mode", ArtifactMode.REFERENCE.value)
        try:
            mode_enum = ArtifactMode(mode_val.lower())
        except (ValueError, AttributeError):
            mode_enum = ArtifactMode.REFERENCE

        raw_path = data.get("path_or_uri") or data.get("path", "")
        fallback_name = Path(raw_path).name or raw_path or "unnamed_artifact"

        return cls(
            name=data.get("name") or fallback_name,
            path_or_uri=raw_path,
            mode=mode_enum,
            captured_at=data.get("captured_at", datetime.now(timezone.utc).isoformat()),
            checksum_sha256=data.get("checksum_sha256"),
            size_bytes=data.get("size_bytes"),
            snapshot_content=data.get("snapshot_content"),
            storage_visibility=data.get("storage_visibility", "workspace_local"),
            is_present=data.get("is_present"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ResumeBrief:
    """
    Derived, actionable summary answering the 6 core continuity questions.
    Generated deterministically and locally by default; not authoritative record.
    """
    purpose: str
    last_completed_work: List[str] = field(default_factory=list)
    key_decisions: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    unresolved_questions: List[str] = field(default_factory=list)
    next_actions: List[str] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_ai_enhanced: bool = False
    generator_id: str = "deterministic_local"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "purpose": self.purpose,
            "last_completed_work": list(self.last_completed_work),
            "key_decisions": list(self.key_decisions),
            "blockers": list(self.blockers),
            "unresolved_questions": list(self.unresolved_questions),
            "next_actions": list(self.next_actions),
            "generated_at": self.generated_at,
            "is_ai_enhanced": self.is_ai_enhanced,
            "generator_id": self.generator_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResumeBrief":
        return cls(
            purpose=data.get("purpose", ""),
            last_completed_work=data.get("last_completed_work", []),
            key_decisions=data.get("key_decisions", []),
            blockers=data.get("blockers", []),
            unresolved_questions=data.get("unresolved_questions", []),
            next_actions=data.get("next_actions", []),
            generated_at=data.get("generated_at", datetime.now(timezone.utc).isoformat()),
            is_ai_enhanced=bool(data.get("is_ai_enhanced", False)),
            generator_id=data.get("generator_id", "deterministic_local"),
        )


@dataclass
class UniversalCheckpoint:
    """
    Durable snapshot of Activity state representing complete, portable continuity.
    Optional fields remain optional, ensuring forward and backward schema resilience.
    """
    id: str
    activity_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    parent_checkpoint_id: Optional[str] = None
    branch_source_checkpoint_id: Optional[str] = None
    structured_state: Dict[str, Any] = field(default_factory=dict)
    progress: Dict[str, Any] = field(default_factory=dict)
    completed_work: List[str] = field(default_factory=list)
    pending_actions: List[str] = field(default_factory=list)
    decisions: List[DecisionRecord] = field(default_factory=list)
    context: str = ""
    references: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    artifacts: List[ArtifactReference] = field(default_factory=list)
    permitted_excerpts: List[str] = field(default_factory=list)
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)
    resume_brief: Optional[ResumeBrief] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Validate ID
        if not self.id or not isinstance(self.id, str) or not self.id.strip():
            raise CheckpointValidationError("Checkpoint 'id' must be a non-empty string.")
        self.id = self.id.strip()

        # Validate activity_id
        if not self.activity_id or not isinstance(self.activity_id, str) or not self.activity_id.strip():
            raise CheckpointValidationError("Checkpoint 'activity_id' must be a non-empty string.")
        self.activity_id = self.activity_id.strip()

        # Ensure provenance is instance of ProvenanceRecord
        if isinstance(self.provenance, dict):
            self.provenance = ProvenanceRecord.from_dict(self.provenance)

        # Ensure decisions are DecisionRecord instances
        parsed_decisions = []
        for d in self.decisions:
            if isinstance(d, dict):
                parsed_decisions.append(DecisionRecord.from_dict(d))
            elif isinstance(d, DecisionRecord):
                parsed_decisions.append(d)
        self.decisions = parsed_decisions

        # Ensure artifacts are ArtifactReference instances
        parsed_artifacts = []
        for a in self.artifacts:
            if isinstance(a, dict):
                parsed_artifacts.append(ArtifactReference.from_dict(a))
            elif isinstance(a, ArtifactReference):
                parsed_artifacts.append(a)
        self.artifacts = parsed_artifacts

        # Ensure resume_brief is ResumeBrief instance if present
        if isinstance(self.resume_brief, dict):
            self.resume_brief = ResumeBrief.from_dict(self.resume_brief)

    def validate(self) -> "UniversalCheckpoint":
        """Explicitly executes validation rules on this UniversalCheckpoint."""
        self.__post_init__()
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Serializes UniversalCheckpoint to dictionary format."""
        return {
            "id": self.id,
            "activity_id": self.activity_id,
            "timestamp": self.timestamp,
            "parent_checkpoint_id": self.parent_checkpoint_id,
            "branch_source_checkpoint_id": self.branch_source_checkpoint_id,
            "structured_state": dict(self.structured_state),
            "progress": dict(self.progress),
            "completed_work": list(self.completed_work),
            "pending_actions": list(self.pending_actions),
            "decisions": [d.to_dict() for d in self.decisions],
            "context": self.context,
            "references": list(self.references),
            "blockers": list(self.blockers),
            "artifacts": [a.to_dict() for a in self.artifacts],
            "permitted_excerpts": list(self.permitted_excerpts),
            "provenance": self.provenance.to_dict(),
            "resume_brief": self.resume_brief.to_dict() if self.resume_brief else None,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UniversalCheckpoint":
        """Reconstructs UniversalCheckpoint from dictionary format."""
        decisions = [DecisionRecord.from_dict(d) for d in data.get("decisions", [])]
        artifacts = [ArtifactReference.from_dict(a) for a in data.get("artifacts", [])]
        provenance = ProvenanceRecord.from_dict(data.get("provenance", {}))
        
        brief_data = data.get("resume_brief")
        resume_brief = ResumeBrief.from_dict(brief_data) if brief_data else None

        return cls(
            id=data["id"],
            activity_id=data["activity_id"],
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            parent_checkpoint_id=data.get("parent_checkpoint_id"),
            branch_source_checkpoint_id=data.get("branch_source_checkpoint_id"),
            structured_state=data.get("structured_state", {}),
            progress=data.get("progress", {}),
            completed_work=data.get("completed_work", []),
            pending_actions=data.get("pending_actions", []),
            decisions=decisions,
            context=data.get("context", ""),
            references=data.get("references", []),
            blockers=data.get("blockers", []),
            artifacts=artifacts,
            permitted_excerpts=data.get("permitted_excerpts", []),
            provenance=provenance,
            resume_brief=resume_brief,
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def create_minimal(
        cls,
        activity_id: str,
        context: str = "",
        custom_id: Optional[str] = None,
        parent_checkpoint_id: Optional[str] = None
    ) -> "UniversalCheckpoint":
        """Factory for minimal valid checkpoint with all optional fields omitted or empty."""
        chk_id = custom_id or f"chk_{uuid.uuid4().hex[:12]}"
        return cls(
            id=chk_id,
            activity_id=activity_id,
            context=context,
            parent_checkpoint_id=parent_checkpoint_id,
        )

    @classmethod
    def from_legacy_handoff_checkpoint(
        cls,
        legacy_data: Union[Dict[str, Any], Any],
        activity_id: Optional[str] = None
    ) -> "UniversalCheckpoint":
        """
        Maps legacy HandoffCheckpoint records into UniversalCheckpoint format.
        Preserves original checkpoint_id, prompt_summary, parent_id, and model metadata.
        """
        if hasattr(legacy_data, "to_dict"):
            d = legacy_data.to_dict()
        else:
            d = dict(legacy_data)

        chk_id = d.get("checkpoint_id") or f"chk_{uuid.uuid4().hex[:12]}"
        act_id = activity_id or d.get("metadata", {}).get("activity_id") or "act_legacy_handoff"
        
        # Build provenance reflecting AI handoff origins
        provenance = ProvenanceRecord(
            provenance_type=ProvenanceType.AUTO_CAPTURED,
            captured_by=d.get("origin_model", "unknown_model"),
            captured_at=d.get("timestamp", datetime.now(timezone.utc).isoformat()),
            is_authoritative=False,
            details={
                "origin_model": d.get("origin_model"),
                "target_model": d.get("target_model"),
                "total_messages": d.get("total_messages", 0),
                "total_code_blocks": d.get("total_code_blocks", 0)
            }
        )

        # Build resume brief from legacy prompt summary if present
        brief = None
        if d.get("prompt_summary"):
            brief = ResumeBrief(
                purpose=d.get("prompt_summary", ""),
                last_completed_work=[f"Handoff from {d.get('origin_model', 'model')} to {d.get('target_model', 'model')}"],
                key_decisions=[],
                blockers=[],
                unresolved_questions=[],
                next_actions=["Review handoff prompt and continue session"],
                generated_at=d.get("timestamp", datetime.now(timezone.utc).isoformat()),
                is_ai_enhanced=True,
                generator_id="legacy_handoff_adapter"
            )

        return cls(
            id=chk_id,
            activity_id=act_id,
            timestamp=d.get("timestamp", datetime.now(timezone.utc).isoformat()),
            parent_checkpoint_id=d.get("parent_checkpoint_id"),
            context=d.get("prompt_summary", ""),
            permitted_excerpts=[d.get("compressed_prompt")] if d.get("compressed_prompt") else [],
            provenance=provenance,
            resume_brief=brief,
            metadata={
                "legacy_handoff": True,
                "origin_model": d.get("origin_model"),
                "target_model": d.get("target_model"),
                "metadata": d.get("metadata", {})
            }
        )
