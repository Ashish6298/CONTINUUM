"""
Project Continuum - Persistent Storage & Git Hook Models
=========================================================
Milestone 7 - Phase 17: Git Hooks & Persistent State Management.
Defines models for storage management, backup metadata, and recovery reports.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class StorageMetadata:
    """Metadata regarding local .continuum/ storage and history."""
    workspace_root: str
    continuum_dir: str
    active_state_file: str
    history_count: int = 0
    backup_count: int = 0
    last_saved_at: Optional[str] = None
    last_snapshot_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RecoveryResult:
    """Result of state integrity check and auto-recovery operation."""
    success: bool
    recovered_from: Optional[str] = None
    error_message: Optional[str] = None
    state_restored: bool = False
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
