"""
Project Continuum - Watcher Package Exports
===========================================
Milestone 7 - Phase 16: Filesystem Observation & Incremental State Updates.
"""

from watcher.models import ChangeType, FileChangeEvent, IncrementalUpdateResult
from watcher.detector import WorkspaceChangeDetector
from watcher.updater import IncrementalStateUpdater

__all__ = [
    "ChangeType",
    "FileChangeEvent",
    "IncrementalUpdateResult",
    "WorkspaceChangeDetector",
    "IncrementalStateUpdater",
]
