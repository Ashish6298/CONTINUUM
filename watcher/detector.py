"""
Project Continuum - Workspace Change Detector
==============================================
Milestone 7 - Phase 16: Filesystem Observation & Incremental State Updates.
Computes filesystem delta sets (creations, modifications, deletions) against
a cached baseline snapshot with built-in ignore filtering.
"""

import hashlib
import os
from pathlib import Path
import time
from typing import Dict, List, Optional, Set, Tuple

from extractors.base import DEFAULT_IGNORE_DIRS
from watcher.models import ChangeType, FileChangeEvent


class WorkspaceChangeDetector:
    """
    Tracks workspace file timestamps and SHA-256 hashes to detect modifications,
    creations, and deletions with high efficiency.
    """

    def __init__(
        self,
        workspace_root: str,
        ignore_dirs: Optional[Set[str]] = None,
        max_file_size_mb: float = 10.0
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.ignore_dirs = ignore_dirs or DEFAULT_IGNORE_DIRS
        self.max_file_size_bytes = int(max_file_size_mb * 1024 * 1024)
        self._baseline_snapshot: Dict[str, Tuple[float, int, str]] = {}  # rel_path -> (mtime, size, hash)

    def compute_current_snapshot(self) -> Dict[str, Tuple[float, int, str]]:
        """
        Walks the workspace and constructs a map of rel_path -> (mtime, size, sha256).
        """
        snapshot: Dict[str, Tuple[float, int, str]] = {}
        if not self.workspace_root.exists():
            return snapshot

        for root, dirs, files in os.walk(self.workspace_root):
            # Prune ignored directories
            dirs[:] = [d for d in dirs if d not in self.ignore_dirs and not d.startswith(".")]

            for file in files:
                full_path = Path(root) / file
                try:
                    stat = full_path.stat()
                    if stat.st_size > self.max_file_size_bytes:
                        continue

                    rel_path = str(full_path.relative_to(self.workspace_root)).replace("\\", "/")
                    mtime = stat.st_mtime
                    size = stat.st_size

                    # Hash only if size or mtime differs from cached snapshot or on first pass
                    cached = self._baseline_snapshot.get(rel_path)
                    if cached and cached[0] == mtime and cached[1] == size:
                        f_hash = cached[2]
                    else:
                        f_hash = self._hash_file(full_path)

                    snapshot[rel_path] = (mtime, size, f_hash)
                except (OSError, PermissionError):
                    continue

        return snapshot

    def initialize_baseline(self) -> int:
        """
        Takes initial baseline snapshot of the workspace.
        Returns number of tracked files.
        """
        self._baseline_snapshot = self.compute_current_snapshot()
        return len(self._baseline_snapshot)

    def detect_changes(self) -> List[FileChangeEvent]:
        """
        Compares current filesystem state against baseline snapshot and returns
        the list of FileChangeEvents, updating the baseline in-place.
        """
        current_snapshot = self.compute_current_snapshot()
        changes: List[FileChangeEvent] = []

        # 1. Check for creations and modifications
        for rel_path, (mtime, size, f_hash) in current_snapshot.items():
            if rel_path not in self._baseline_snapshot:
                changes.append(
                    FileChangeEvent(
                        file_path=rel_path,
                        change_type=ChangeType.CREATED,
                        file_hash=f_hash,
                        file_size_bytes=size
                    )
                )
            else:
                base_mtime, base_size, base_hash = self._baseline_snapshot[rel_path]
                if f_hash != base_hash:
                    changes.append(
                        FileChangeEvent(
                            file_path=rel_path,
                            change_type=ChangeType.MODIFIED,
                            file_hash=f_hash,
                            file_size_bytes=size
                        )
                    )

        # 2. Check for deletions
        for rel_path, (base_mtime, base_size, base_hash) in self._baseline_snapshot.items():
            if rel_path not in current_snapshot:
                changes.append(
                    FileChangeEvent(
                        file_path=rel_path,
                        change_type=ChangeType.DELETED,
                        file_hash=base_hash,
                        file_size_bytes=base_size
                    )
                )

        # Update baseline to current snapshot
        self._baseline_snapshot = current_snapshot
        return changes

    def _hash_file(self, path: Path) -> str:
        """Calculates SHA-256 hash of file content."""
        hasher = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (OSError, PermissionError):
            return ""
