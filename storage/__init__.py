"""
Project Continuum - Storage Subsystem Exports
=============================================
Milestone 7 - Phase 17: Git Hooks & Persistent State Management.
"""

from storage.models import StorageMetadata, RecoveryResult
from storage.manager import ContinuumStorageManager
from storage.recovery import StateRecoveryManager
from storage.hooks import GitHookManager
from storage.activity_store import (
    ActivityCheckpointStore,
    ActivityNotFoundError,
    CheckpointNotFoundError,
    DanglingReferenceError,
)
from storage.migration import (
    ContinuumMigrator,
    MigrationResult,
    MigrationRecord,
    CURRENT_SCHEMA_VERSION,
)
from storage.consistency import (
    ConsistencyIssueType,
    ConsistencyIssue,
    ConsistencyAuditReport,
    ConsistencyRepairResult,
    StorageConsistencyEngine,
)

__all__ = [
    "StorageMetadata",
    "RecoveryResult",
    "ContinuumStorageManager",
    "StateRecoveryManager",
    "GitHookManager",
    "ActivityCheckpointStore",
    "ActivityNotFoundError",
    "CheckpointNotFoundError",
    "DanglingReferenceError",
    "ContinuumMigrator",
    "MigrationResult",
    "MigrationRecord",
    "CURRENT_SCHEMA_VERSION",
    "ConsistencyIssueType",
    "ConsistencyIssue",
    "ConsistencyAuditReport",
    "ConsistencyRepairResult",
    "StorageConsistencyEngine",
]
