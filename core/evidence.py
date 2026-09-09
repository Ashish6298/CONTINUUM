"""
Project Continuum - Canonical Evidence Model & Provenance
=========================================================
Implements the canonical Evidence data structure used by every extractor
and resolver across Project Continuum.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional
import uuid

from core.enums import EvidenceType, EvidenceLevel


@dataclass
class EvidenceProvenance:
    """
    Detailed audit trace explaining how and where evidence was obtained.
    """
    extractor_name: str
    source_uri: str
    locator: str  # e.g., "line:42-88", "symbol:AuthService.verify", "git:a1b2c3d", "turn:4"
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    environment_info: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceProvenance":
        return cls(
            extractor_name=data.get("extractor_name", "unknown_extractor"),
            source_uri=data.get("source_uri", ""),
            locator=data.get("locator", ""),
            collected_at=data.get("collected_at", datetime.now(timezone.utc).isoformat()),
            environment_info=data.get("environment_info", {})
        )


@dataclass
class Evidence:
    """
    The canonical unit of proof in Project Continuum.
    Every conclusion, confidence score, and status assessment must be grounded
    in verifiable Evidence records.
    """
    id: str = field(default_factory=lambda: f"ev_{uuid.uuid4().hex[:12]}")
    type: EvidenceType = EvidenceType.SOURCE_CODE
    level: EvidenceLevel = EvidenceLevel.LEVEL_2_CODE_AST
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    provenance: Optional[EvidenceProvenance] = None
    checksum: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Normalize types if strings were passed
        if isinstance(self.type, str):
            self.type = EvidenceType(self.type)
        if isinstance(self.level, int) and not isinstance(self.level, EvidenceLevel):
            self.level = EvidenceLevel(self.level)
        elif self.level is None:
            self.level = EvidenceLevel.get_level_for_type(self.type)

        # Auto-calculate checksum of raw_payload if empty
        if not self.checksum:
            self.checksum = self.calculate_checksum()

    def calculate_checksum(self) -> str:
        """Calculates deterministic SHA-256 hash of the evidence payload & summary."""
        normalized_dict = {
            "type": self.type.value if hasattr(self.type, "value") else str(self.type),
            "summary": self.summary,
            "raw_payload": self.raw_payload,
            "provenance": self.provenance.to_dict() if self.provenance else None
        }
        serialized = json.dumps(normalized_dict, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def verify_integrity(self) -> bool:
        """Checks if current payload matches recorded checksum."""
        return self.checksum == self.calculate_checksum()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "level": int(self.level.value),
            "summary": self.summary,
            "raw_payload": self.raw_payload,
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "checksum": self.checksum,
            "created_at": self.created_at,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Evidence":
        ev_type = EvidenceType(data["type"])
        ev_level = EvidenceLevel(data.get("level", EvidenceLevel.get_level_for_type(ev_type).value))
        provenance = EvidenceProvenance.from_dict(data["provenance"]) if data.get("provenance") else None

        return cls(
            id=data.get("id", f"ev_{uuid.uuid4().hex[:12]}"),
            type=ev_type,
            level=ev_level,
            summary=data.get("summary", ""),
            raw_payload=data.get("raw_payload", {}),
            provenance=provenance,
            checksum=data.get("checksum", ""),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            metadata=data.get("metadata", {})
        )
