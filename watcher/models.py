"""
Project Continuum - Filesystem Observation & Incremental State Models
======================================================================
Milestone 7 - Phase 16: Filesystem Observation & Incremental State Updates.
Defines change event structures and incremental update result containers.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class ChangeType(str, Enum):
    """Types of filesystem change events."""
    CREATED = "CREATED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"


@dataclass
class FileChangeEvent:
    """Represents a discrete filesystem modification event."""
    file_path: str
    change_type: ChangeType
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    file_hash: Optional[str] = None
    file_size_bytes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["change_type"] = self.change_type.value
        return d


@dataclass
class IncrementalUpdateResult:
    """
    Summary of an incremental state update cycle.
    """
    workspace_root: str
    changes_processed: List[FileChangeEvent] = field(default_factory=list)
    re_extracted_symbols_count: int = 0
    removed_symbols_count: int = 0
    invalidated_node_ids: List[str] = field(default_factory=list)
    propagated_stale_node_ids: List[str] = field(default_factory=list)
    full_scan_fallback_triggered: bool = False
    duration_ms: float = 0.0
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workspace_root": self.workspace_root,
            "changes_processed": [c.to_dict() for c in self.changes_processed],
            "re_extracted_symbols_count": self.re_extracted_symbols_count,
            "removed_symbols_count": self.removed_symbols_count,
            "invalidated_node_ids": self.invalidated_node_ids,
            "propagated_stale_node_ids": self.propagated_stale_node_ids,
            "full_scan_fallback_triggered": self.full_scan_fallback_triggered,
            "duration_ms": self.duration_ms,
            "updated_at": self.updated_at
        }
