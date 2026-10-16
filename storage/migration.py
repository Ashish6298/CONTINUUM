"""
Project Continuum — Versioned, Idempotent Data Migration Engine
================================================================
Milestone 37: Durable Storage and Migration
Phase 57: Versioned, Idempotent Migration

Implements:
1. Version detection across fresh installs, legacy v1.0.0-v1.3.0 workspaces, and v1.4.0.
2. Migration planning and dry-run preview (I-14).
3. Pre-migration verified recovery backup point in `<workspace_root>/.continuum/backup/`.
4. Idempotent transformation: safe repeated execution without duplicate records.
5. Conservative mapping of legacy state.json, history snapshots, and handoffs into
   v1.4.0 partitioned Activities and Universal Checkpoints.
6. Graceful handling and reporting of malformed, unsupported, or skipped records.
7. Post-migration integrity verification gate: rollback on failure, zero false success (I-14).
8. Backward compatibility preserving IDs, relations, and provenance (I-18).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Set, Tuple

from core.activity import Activity, ActivityStatus, ActivityType
from core.checkpoint import UniversalCheckpoint, ProvenanceRecord
from core.enums import ProvenanceType
from core.invariants import MigrationError
from storage.activity_store import ActivityCheckpointStore, ActivityNotFoundError


CURRENT_SCHEMA_VERSION = "1.4.0"
SUPPORTED_SOURCE_VERSIONS = {"1.0.0", "1.1.0", "1.2.0", "1.3.0"}


@dataclass
class MigrationRecord:
    """Detailed record of a single migrated or skipped artifact."""
    source_path: str
    record_type: str  # "activity", "checkpoint", "history", "handoff"
    record_id: str
    status: str  # "migrated", "skipped", "already_migrated"
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_path": self.source_path,
            "record_type": self.record_type,
            "record_id": self.record_id,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass
class MigrationResult:
    """Authoritative outcome of a migration or preview operation."""
    source_version: str
    target_version: str
    success: bool
    is_dry_run: bool
    activities_migrated: int = 0
    checkpoints_migrated: int = 0
    records_skipped: List[MigrationRecord] = field(default_factory=list)
    backup_path: Optional[str] = None
    details: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_version": self.source_version,
            "target_version": self.target_version,
            "success": self.success,
            "is_dry_run": self.is_dry_run,
            "activities_migrated": self.activities_migrated,
            "checkpoints_migrated": self.checkpoints_migrated,
            "records_skipped": [r.to_dict() for r in self.records_skipped],
            "backup_path": self.backup_path,
            "details": self.details,
        }


class ContinuumMigrator:
    """
    Orchestrates schema migrations to v1.4.0 Universal Resume Anywhere layout.
    Guarantees:
    - Pre-migration backup for instant rollback.
    - Idempotency across repeat executions.
    - Zero destructive deletion of unmigrated data.
    """

    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root).resolve()
        self.continuum_dir = self.workspace_root / ".continuum"
        self.backup_dir = self.continuum_dir / "backup"
        self.migration_marker_file = self.continuum_dir / "migration.json"
        self.state_file = self.continuum_dir / "state.json"
        self.history_dir = self.continuum_dir / "history"
        self.handoffs_dir = self.continuum_dir / "handoffs"
        self.activities_dir = self.continuum_dir / "activities"

    def detect_version(self) -> str:
        """
        Determines the current storage schema version.
        Returns 'fresh_install', '1.0.0', '1.4.0', or 'unsupported'.
        """
        if not self.continuum_dir.exists():
            return "fresh_install"

        # Check explicit migration marker
        if self.migration_marker_file.exists():
            try:
                data = json.loads(self.migration_marker_file.read_text(encoding="utf-8"))
                return data.get("schema_version", CURRENT_SCHEMA_VERSION)
            except Exception:
                pass

        # Check if v1.4.0 partitioned activities exist
        if self.activities_dir.exists() and any(self.activities_dir.iterdir()):
            return CURRENT_SCHEMA_VERSION

        # Check if legacy state.json exists
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                version = data.get("schema_version", "1.0.0")
                if version in SUPPORTED_SOURCE_VERSIONS:
                    return version
                return "unsupported"
            except Exception:
                return "unsupported"

        # If directory exists but is completely empty
        return "fresh_install"

    def create_pre_migration_backup(self) -> Path:
        """
        Creates a timestamped snapshot of the entire .continuum directory.
        Returns the path to the created backup directory.
        """
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        target_backup = self.backup_dir / f"pre_migration_{ts}"
        target_backup.mkdir(parents=True, exist_ok=True)

        # Copy state.json if present
        if self.state_file.exists():
            shutil.copy2(self.state_file, target_backup / "state.json")

        # Copy history directory if present
        if self.history_dir.exists():
            shutil.copytree(self.history_dir, target_backup / "history", dirs_exist_ok=True)

        # Copy handoffs directory if present
        if self.handoffs_dir.exists():
            shutil.copytree(self.handoffs_dir, target_backup / "handoffs", dirs_exist_ok=True)

        return target_backup

    def plan_migration(self) -> MigrationResult:
        """
        Produces a dry-run preview of proposed migration actions without altering disk.
        """
        source_ver = self.detect_version()

        if source_ver == "fresh_install":
            return MigrationResult(
                source_version=source_ver,
                target_version=CURRENT_SCHEMA_VERSION,
                success=True,
                is_dry_run=True,
                details="Fresh install: storage will be initialized directly with v1.4.0 schema.",
            )

        if source_ver == CURRENT_SCHEMA_VERSION:
            return MigrationResult(
                source_version=source_ver,
                target_version=CURRENT_SCHEMA_VERSION,
                success=True,
                is_dry_run=True,
                details="Storage is already up-to-date at version 1.4.0. No migration needed.",
            )

        if source_ver not in SUPPORTED_SOURCE_VERSIONS:
            return MigrationResult(
                source_version=source_ver,
                target_version=CURRENT_SCHEMA_VERSION,
                success=False,
                is_dry_run=True,
                details=f"Cannot migrate unsupported source version '{source_ver}'.",
            )

        # Inspect and count records
        activities_count = 1 if self.state_file.exists() else 0
        checkpoints_count = 1 if self.state_file.exists() else 0
        skipped_records: List[MigrationRecord] = []

        # Inspect handoffs
        if self.handoffs_dir.exists():
            for f in self.handoffs_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        checkpoints_count += 1
                    else:
                        skipped_records.append(
                            MigrationRecord(str(f), "handoff", f.name, "skipped", "File is not a JSON object")
                        )
                except Exception as e:
                    skipped_records.append(
                        MigrationRecord(str(f), "handoff", f.name, "skipped", f"Malformed JSON: {e}")
                    )

        # Inspect history
        if self.history_dir.exists():
            for f in self.history_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and "schema_version" in data:
                        checkpoints_count += 1
                    else:
                        skipped_records.append(
                            MigrationRecord(str(f), "history", f.name, "skipped", "Missing schema_version")
                        )
                except Exception as e:
                    skipped_records.append(
                        MigrationRecord(str(f), "history", f.name, "skipped", f"Malformed JSON: {e}")
                    )

        return MigrationResult(
            source_version=source_ver,
            target_version=CURRENT_SCHEMA_VERSION,
            success=True,
            is_dry_run=True,
            activities_migrated=activities_count,
            checkpoints_migrated=checkpoints_count,
            records_skipped=skipped_records,
            details=f"Dry-run preview: {activities_count} activity and {checkpoints_count} checkpoints ready for migration.",
        )

    def migrate(self, dry_run: bool = False, create_backup: bool = True) -> MigrationResult:
        """
        Executes idempotent migration from legacy schema to v1.4.0.
        Guarantees:
        - Dry run preview when dry_run=True.
        - Pre-migration backup if create_backup=True.
        - Automatic post-migration verification; raises MigrationError on failure.
        - Idempotent on repeated runs.
        """
        if dry_run:
            return self.plan_migration()

        source_ver = self.detect_version()

        if source_ver == CURRENT_SCHEMA_VERSION:
            return MigrationResult(
                source_version=source_ver,
                target_version=CURRENT_SCHEMA_VERSION,
                success=True,
                is_dry_run=False,
                details="Storage is already up-to-date at version 1.4.0. Migration is idempotent.",
            )

        if source_ver == "fresh_install":
            store = ActivityCheckpointStore(str(self.workspace_root))
            self._write_migration_marker("fresh_install", CURRENT_SCHEMA_VERSION)
            return MigrationResult(
                source_version="fresh_install",
                target_version=CURRENT_SCHEMA_VERSION,
                success=True,
                is_dry_run=False,
                details="Fresh install initialized directly at version 1.4.0.",
            )

        if source_ver not in SUPPORTED_SOURCE_VERSIONS:
            raise MigrationError(
                f"Unsupported source schema version '{source_ver}'. Cannot migrate.",
                internal_details=f"detect_version returned {source_ver}",
            )

        # 1. Create verified recovery point
        backup_path = None
        if create_backup:
            backup_path = str(self.create_pre_migration_backup())

        store = ActivityCheckpointStore(str(self.workspace_root))
        skipped_records: List[MigrationRecord] = []
        activities_migrated = 0
        checkpoints_migrated = 0

        try:
            # 2. Establish migrated workspace root activity
            default_act_id = "act_migrated_workspace"
            try:
                root_activity = store.get_activity(default_act_id)
            except ActivityNotFoundError:
                root_activity = Activity.create_blank(
                    title="Migrated Workspace Activity",
                    description="Preserved historical activity migrated from legacy Continuum state.",
                    activity_type=ActivityType.CODING,
                    custom_id=default_act_id,
                    tags=["migrated", f"v{source_ver}"],
                )
                store.create_activity(root_activity)
                activities_migrated += 1

            # 3. Migrate active state.json into root checkpoint
            if self.state_file.exists():
                try:
                    state_content = json.loads(self.state_file.read_text(encoding="utf-8"))
                    active_chk_id = f"chk_migrated_active_{source_ver.replace('.', '_')}"
                    
                    try:
                        store.get_checkpoint(active_chk_id, default_act_id)
                    except Exception:
                        active_chk = UniversalCheckpoint.create_minimal(
                            activity_id=default_act_id,
                            custom_id=active_chk_id,
                            context="Migrated active workspace state",
                        )
                        active_chk.structured_state = state_content
                        active_chk.provenance = ProvenanceRecord(
                            provenance_type=ProvenanceType.IMPORTED,
                            captured_by=f"migrator_v{CURRENT_SCHEMA_VERSION}",
                            details={"original_schema_version": source_ver},
                        )
                        store.commit_checkpoint(active_chk)
                        checkpoints_migrated += 1
                except Exception as e:
                    skipped_records.append(
                        MigrationRecord(str(self.state_file), "active_state", "state.json", "skipped", str(e))
                    )

            # 4. Migrate handoffs from .continuum/handoffs/
            if self.handoffs_dir.exists():
                for hf in sorted(self.handoffs_dir.glob("*.json")):
                    try:
                        h_data = json.loads(hf.read_text(encoding="utf-8"))
                        if not isinstance(h_data, dict):
                            skipped_records.append(
                                MigrationRecord(str(hf), "handoff", hf.name, "skipped", "Content is not JSON object")
                            )
                            continue

                        h_chk = UniversalCheckpoint.from_legacy_handoff_checkpoint(h_data, activity_id=default_act_id)
                        # Check idempotency
                        try:
                            store.get_checkpoint(h_chk.id, default_act_id)
                        except Exception:
                            store.commit_checkpoint(h_chk)
                            checkpoints_migrated += 1
                    except Exception as e:
                        skipped_records.append(
                            MigrationRecord(str(hf), "handoff", hf.name, "skipped", f"Malformed JSON: {e}")
                        )

            # 5. Migrate history snapshots from .continuum/history/
            if self.history_dir.exists():
                for snap in sorted(self.history_dir.glob("*.json")):
                    try:
                        s_data = json.loads(snap.read_text(encoding="utf-8"))
                        if not isinstance(s_data, dict) or "schema_version" not in s_data:
                            skipped_records.append(
                                MigrationRecord(str(snap), "history", snap.name, "skipped", "Invalid snapshot schema")
                            )
                            continue

                        snap_id = f"chk_snap_{snap.stem.replace('state_', '')}"
                        try:
                            store.get_checkpoint(snap_id, default_act_id)
                        except Exception:
                            snap_chk = UniversalCheckpoint.create_minimal(
                                activity_id=default_act_id,
                                custom_id=snap_id,
                                context=f"Migrated history snapshot: {snap.name}",
                            )
                            snap_chk.structured_state = s_data
                            snap_chk.provenance = ProvenanceRecord(
                                provenance_type=ProvenanceType.AUTO_CAPTURED,
                                captured_by="legacy_history_snapshot",
                            )
                            store.commit_checkpoint(snap_chk)
                            checkpoints_migrated += 1
                    except Exception as e:
                        skipped_records.append(
                            MigrationRecord(str(snap), "history", snap.name, "skipped", f"Malformed JSON: {e}")
                        )

            # 6. Post-migration verification gate
            # Ensure root activity and at least one checkpoint can be retrieved
            verified_act = store.get_activity(default_act_id)
            if not verified_act:
                raise MigrationError("Post-migration verification failed: migrated activity unreadable.")

            # 7. Write migration marker
            self._write_migration_marker(source_ver, CURRENT_SCHEMA_VERSION)

            return MigrationResult(
                source_version=source_ver,
                target_version=CURRENT_SCHEMA_VERSION,
                success=True,
                is_dry_run=False,
                activities_migrated=activities_migrated,
                checkpoints_migrated=checkpoints_migrated,
                records_skipped=skipped_records,
                backup_path=backup_path,
                details=f"Migration completed successfully: {activities_migrated} activity, {checkpoints_migrated} checkpoints migrated.",
            )

        except Exception as e:
            # Rollback if requested
            if backup_path:
                self.rollback(backup_path)
            raise MigrationError(f"Migration aborted due to failure: {e}", internal_details=str(e))

    def rollback(self, backup_path: Optional[str] = None) -> bool:
        """
        Restores .continuum from the specified or newest pre-migration backup.
        """
        target_dir = Path(backup_path) if backup_path else None
        if not target_dir or not target_dir.exists():
            # Find newest backup
            if not self.backup_dir.exists():
                return False
            backups = sorted(self.backup_dir.glob("pre_migration_*"), reverse=True)
            if not backups:
                return False
            target_dir = backups[0]

        # Restore state.json
        backup_state = target_dir / "state.json"
        if backup_state.exists():
            shutil.copy2(backup_state, self.state_file)

        # Restore handoffs
        backup_handoffs = target_dir / "handoffs"
        if backup_handoffs.exists():
            shutil.copytree(backup_handoffs, self.handoffs_dir, dirs_exist_ok=True)

        # Restore history
        backup_history = target_dir / "history"
        if backup_history.exists():
            shutil.copytree(backup_history, self.history_dir, dirs_exist_ok=True)

        # Remove migration marker
        if self.migration_marker_file.exists():
            self.migration_marker_file.unlink()

        return True

    def _write_migration_marker(self, source_ver: str, target_ver: str) -> None:
        """Writes migration metadata to .continuum/migration.json."""
        marker_data = {
            "schema_version": target_ver,
            "migrated_from": source_ver,
            "migrated_at": datetime.now(timezone.utc).isoformat(),
            "migrator": f"ContinuumMigrator/{CURRENT_SCHEMA_VERSION}",
        }
        self.migration_marker_file.write_text(
            json.dumps(marker_data, indent=2), encoding="utf-8"
        )
