"""
Project Continuum - Persistent Storage Manager
==============================================
Milestone 7 - Phase 17: Git Hooks & Persistent State Management.
Manages the local `.continuum/` directory structure, versioned history snapshots,
and atomic state file persistence.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import time
from typing import Any, Dict, List, Optional

from core.schema import validate_canonical_state_dict
from core.serializer import CanonicalStateSerializer
from core.state_models import CanonicalProjectState
from storage.models import StorageMetadata


class ContinuumStorageManager:
    """
    Manages persistent state on disk inside `<workspace_root>/.continuum/`:
    - `.continuum/state.json`: Active canonical project state
    - `.continuum/history/`: Versioned snapshots (timestamped)
    - `.continuum/backup/`: Pre-modification safety backups
    """

    MAX_HISTORY_SNAPSHOTS = 100

    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root).resolve()
        self.continuum_dir = self.workspace_root / ".continuum"
        self.history_dir = self.continuum_dir / "history"
        self.backup_dir = self.continuum_dir / "backup"
        self.active_state_file = self.continuum_dir / "state.json"

    def initialize_storage(self) -> None:
        """Ensures .continuum directory and subfolders exist."""
        self.continuum_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def save_state(
        self,
        state: CanonicalProjectState,
        create_history_snapshot: bool = True,
        commit_tag: Optional[str] = None
    ) -> str:
        """
        Atomically saves state to .continuum/state.json, backing up the previous
        state and optionally storing a versioned history snapshot.
        Returns the path of the saved active state file.
        """
        self.initialize_storage()

        # 1. Backup existing active state if present
        if self.active_state_file.exists():
            backup_target = self.backup_dir / "state.json.bak"
            shutil.copy2(self.active_state_file, backup_target)

        # 2. Write state atomically to active_state_file
        CanonicalStateSerializer.save_to_file(state, self.active_state_file, indent=2)

        # 3. Create versioned history snapshot if requested
        if create_history_snapshot:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            tag_suffix = f"_{commit_tag}" if commit_tag else ""
            snapshot_filename = f"state_{ts}{tag_suffix}.json"
            snapshot_path = self.history_dir / snapshot_filename
            CanonicalStateSerializer.save_to_file(state, snapshot_path, indent=2)
            self._prune_history()

        return str(self.active_state_file.resolve())

    def load_state(self, validate: bool = True) -> CanonicalProjectState:
        """
        Loads and deserializes the active state from .continuum/state.json.
        Raises FileNotFoundError if no active state exists.
        """
        if not self.active_state_file.exists():
            raise FileNotFoundError(f"No active Continuum state found at {self.active_state_file}")

        return CanonicalStateSerializer.load_from_file(self.active_state_file, validate=validate)

    def state_exists(self) -> bool:
        """Checks if active state file exists."""
        return self.active_state_file.exists()

    def get_metadata(self) -> StorageMetadata:
        """Returns metadata regarding active storage, history count, and backups."""
        history_files = list(self.history_dir.glob("state_*.json")) if self.history_dir.exists() else []
        backup_files = list(self.backup_dir.glob("*.bak")) if self.backup_dir.exists() else []

        last_saved = None
        if self.active_state_file.exists():
            last_saved = datetime.fromtimestamp(
                self.active_state_file.stat().st_mtime, timezone.utc
            ).isoformat()

        return StorageMetadata(
            workspace_root=str(self.workspace_root),
            continuum_dir=str(self.continuum_dir),
            active_state_file=str(self.active_state_file),
            history_count=len(history_files),
            backup_count=len(backup_files),
            last_saved_at=last_saved
        )

    def list_history_snapshots(self) -> List[Path]:
        """Returns sorted list of history snapshot filepaths (newest first)."""
        if not self.history_dir.exists():
            return []
        snapshots = list(self.history_dir.glob("state_*.json"))
        return sorted(snapshots, key=lambda p: p.name, reverse=True)

    def _prune_history(self) -> None:
        """Prunes history directory if count exceeds MAX_HISTORY_SNAPSHOTS."""
        snapshots = self.list_history_snapshots()
        if len(snapshots) > self.MAX_HISTORY_SNAPSHOTS:
            for excess in snapshots[self.MAX_HISTORY_SNAPSHOTS:]:
                try:
                    excess.unlink()
                except OSError:
                    pass
