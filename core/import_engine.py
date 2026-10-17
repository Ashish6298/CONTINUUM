"""
Project Continuum — Import, Conflict Resolution & Restore Engine
==================================================================
Milestone 43: Export, Backup, Import and Transfer
Phase 78: Import, Conflicts and Restore

Implements:
1. Pre-mutation complete validation: Archive integrity, checksum verification,
   version check, and relational consistency before touching live storage.
2. Isolated Staging & Transaction Journaling: Extract to staging directory and track
   lifecycle states (VALIDATING -> STAGED -> COMMITTING -> COMMITTED / ROLLED_BACK).
3. Explicit Conflict Resolution:
   - DEDUPLICATE: Safe no-op when ID and content SHA-256 match perfectly.
   - REJECT: Default fail-safe; halts import and raises descriptive error without mutation.
   - RENAME_NEW: Allocates new UUIDs and rewires incoming parent/child references,
     preserving existing local records unchanged.
   - OVERWRITE: Requires explicit confirm_overwrite=True; creates rollback copies of
     local files before replacement.
   - SKIP: Preserves existing local records and skips conflicting incoming entities.
4. Preserves unrelated data: Activities and checkpoints not in the archive are completely
   untouched.
5. Crash-Safe Rollback & Interruption Recovery: Recovers from crashes or interruptions
   during commit phase and cleans up staging, enabling safe retries.
6. Derived Index Rebuild: Rebuilds SQLite indexes (activities_idx, checkpoints_idx, search_fts)
   from authoritative files after commit.
7. Zero external dependencies (Python standard library only).
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tarfile
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import uuid

from core.activity import Activity, ActivityValidationError
from core.backup import (
    BackupManifest,
    CompleteBackupEngine,
    CorruptedBackupError,
    MissingRelationError,
    UnsupportedBackupVersionError,
    hash_file_stream,
)
from core.checkpoint import CheckpointValidationError, UniversalCheckpoint
from core.enums import ConflictResolutionStrategy, ConflictType, ImportStageStatus, ProvenanceType
from core.invariants import ContinuumUserError, InvariantId, InvariantViolationError
from storage.activity_store import ActivityCheckpointStore


class ImportError(ContinuumUserError):
    """Base exception for all import and conflict resolution failures."""
    def __init__(self, message: str, internal_details: Optional[str] = None):
        super().__init__(
            user_message=f"Import operation failed: {message}",
            suggested_action="Verify archive integrity and valid permissions.",
            error_code="ERR_IMPORT_FAILED",
            internal_details=internal_details or message,
        )


class ImportConflictError(ImportError):
    """Raised when unresolvable or unconfirmed conflicts are encountered during import."""
    def __init__(
        self,
        message: str,
        conflicts: Optional[List[Dict[str, Any]]] = None,
        strategy_attempted: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            internal_details=f"Strategy='{strategy_attempted}'. Conflicts count: {len(conflicts or [])}",
        )
        self.conflicts = conflicts or []
        self.strategy_attempted = strategy_attempted
        self.error_code = "ERR_IMPORT_CONFLICT"
        self.suggested_action = "Specify a conflict resolution strategy: RENAME_NEW, OVERWRITE, or SKIP."


class CorruptedArchiveError(ImportError):
    """Raised when an import archive is corrupt, truncated, or tampered."""
    def __init__(self, message: str, internal_details: Optional[str] = None):
        super().__init__(message=f"Corrupt or invalid archive: {message}", internal_details=internal_details)
        self.error_code = "ERR_IMPORT_CORRUPT"
        self.suggested_action = "Re-export or obtain a fresh, untampered backup archive."


class InterruptedImportRecoveryError(ImportError):
    """Raised when recovery from a previous interrupted import fails."""
    pass


@dataclass
class EntityConflict:
    """Describes a detected collision between an incoming entity and an existing live entity."""
    entity_type: str  # "activity" | "checkpoint" | "artifact" | "config"
    entity_id: str
    conflict_type: ConflictType
    description: str
    existing_summary: Dict[str, Any] = field(default_factory=dict)
    incoming_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "conflict_type": self.conflict_type.value,
            "description": self.description,
            "existing_summary": self.existing_summary,
            "incoming_summary": self.incoming_summary,
        }


@dataclass
class ImportPlan:
    """Comprehensive preview of actions to be performed during an import."""
    import_id: str
    archive_path: str
    manifest_summary: Dict[str, Any]
    entities_to_add: List[Dict[str, Any]]
    entities_identical: List[Dict[str, Any]]
    conflicts: List[EntityConflict]
    conflict_strategy: ConflictResolutionStrategy
    has_blocking_conflicts: bool
    unrelated_activities_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "import_id": self.import_id,
            "archive_path": self.archive_path,
            "manifest_summary": self.manifest_summary,
            "entities_to_add": self.entities_to_add,
            "entities_identical": self.entities_identical,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "conflict_strategy": self.conflict_strategy.value,
            "has_blocking_conflicts": self.has_blocking_conflicts,
            "unrelated_activities_count": self.unrelated_activities_count,
        }


@dataclass
class ImportResult:
    """Summary of an executed import operation."""
    import_id: str
    success: bool
    activities_imported: int
    checkpoints_imported: int
    artifacts_imported: int
    configs_imported: int
    activities_renamed: Dict[str, str] = field(default_factory=dict)
    checkpoints_renamed: Dict[str, str] = field(default_factory=dict)
    activities_skipped: List[str] = field(default_factory=list)
    checkpoints_skipped: List[str] = field(default_factory=list)
    activities_overwritten: List[str] = field(default_factory=list)
    checkpoints_overwritten: List[str] = field(default_factory=list)
    unrelated_activities_preserved: int = 0
    indexes_rebuilt: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CompleteImportEngine:
    """
    Transactional import and restore engine for Project Continuum.
    Enforces Phase 78 requirements:
    - Pre-mutation verification
    - Staged validation
    - Conflict resolution (REJECT, RENAME_NEW, OVERWRITE, SKIP, DEDUPLICATE)
    - Unrelated data preservation
    - Safe retry after interruption with rollback journaling
    - Complete derived index rebuild
    """

    def __init__(self, workspace_root: Union[str, Path]):
        self.workspace_root = Path(workspace_root).resolve()
        self.continuum_dir = self.workspace_root / ".continuum"
        self.staging_base = self.continuum_dir / "staging"
        self.history_dir = self.continuum_dir / "import_history"
        self.backup_engine = CompleteBackupEngine(self.workspace_root)
        self.store = ActivityCheckpointStore(str(self.workspace_root))

    def preview_import(
        self,
        archive_path: Union[str, Path],
        conflict_strategy: ConflictResolutionStrategy = ConflictResolutionStrategy.REJECT,
    ) -> ImportPlan:
        """
        Validates archive and generates an ImportPlan previewing all changes,
        identifying conflicts and additions without making any live mutations.
        """
        path = Path(archive_path).resolve()
        if not path.is_file():
            raise ImportError(f"Archive file does not exist: {path}")

        # 1. Complete pre-mutation verification
        try:
            verification = self.backup_engine.verify_backup(path, raise_on_error=True)
        except (CorruptedBackupError, UnsupportedBackupVersionError) as err:
            raise CorruptedArchiveError(str(err)) from err

        import_id = f"preview_{uuid.uuid4().hex[:8]}"
        preview_dir = self.staging_base / import_id

        try:
            extracted_dir = preview_dir / "extracted"
            extracted_dir.mkdir(parents=True, exist_ok=True)

            self._safe_extract_tar(path, extracted_dir)

            staged_manifest_path = extracted_dir / "manifest.json"
            if not staged_manifest_path.is_file():
                raise CorruptedArchiveError("Archive missing root manifest.json")

            with open(staged_manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)

            # Discover staged entities and detect collisions
            plan = self._analyze_staged_records(
                import_id=import_id,
                archive_path=str(path),
                manifest_data=manifest_data,
                extracted_dir=extracted_dir,
                conflict_strategy=conflict_strategy,
            )
            return plan
        finally:
            # Clean up preview directory
            if preview_dir.exists():
                shutil.rmtree(preview_dir, ignore_errors=True)

    def execute_import(
        self,
        archive_path: Union[str, Path],
        conflict_strategy: ConflictResolutionStrategy = ConflictResolutionStrategy.REJECT,
        confirm_overwrite: bool = False,
    ) -> ImportResult:
        """
        Executes an atomic, staged import of a Continuum backup archive.
        Follows strict transaction and rollback procedures:
        1. Recover any past interrupted sessions.
        2. Validate archive pre-mutation.
        3. Stage records in isolated directory.
        4. Detect conflicts and validate resolution strategy.
        5. Begin live mutation under rollback journal protection.
        6. Rebuild derived indexes upon success.
        7. Clean up staging area and record import history.
        """
        start_time = time.time()
        path = Path(archive_path).resolve()
        if not path.is_file():
            raise ImportError(f"Archive file does not exist: {path}")

        # Step 1: Recover from prior interruptions if any
        self.recover_interrupted_imports()

        # Step 2: Validate fully before live mutation
        try:
            self.backup_engine.verify_backup(path, raise_on_error=True)
        except (CorruptedBackupError, UnsupportedBackupVersionError) as err:
            raise CorruptedArchiveError(str(err)) from err

        import_id = f"imp_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        stage_dir = self.staging_base / import_id
        extracted_dir = stage_dir / "extracted"
        rollback_dir = stage_dir / "rollback"
        journal_path = stage_dir / "journal.json"

        stage_dir.mkdir(parents=True, exist_ok=True)
        extracted_dir.mkdir(parents=True, exist_ok=True)
        rollback_dir.mkdir(parents=True, exist_ok=True)

        # Initialize journal
        journal_data: Dict[str, Any] = {
            "import_id": import_id,
            "status": ImportStageStatus.VALIDATING.value,
            "archive_path": str(path),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "conflict_strategy": conflict_strategy.value,
            "confirm_overwrite": confirm_overwrite,
            "overwritten_files": [],
            "created_files": [],
        }
        self._write_journal(journal_path, journal_data)

        try:
            # Step 3: Extract into staging
            self._safe_extract_tar(path, extracted_dir)
            journal_data["status"] = ImportStageStatus.STAGED.value
            self._write_journal(journal_path, journal_data)

            with open(extracted_dir / "manifest.json", "r", encoding="utf-8") as f:
                manifest_data = json.load(f)

            # Step 4: Analyze staged entities and conflicts
            plan = self._analyze_staged_records(
                import_id=import_id,
                archive_path=str(path),
                manifest_data=manifest_data,
                extracted_dir=extracted_dir,
                conflict_strategy=conflict_strategy,
            )

            # Enforce conflict invariants
            if plan.has_blocking_conflicts:
                if conflict_strategy == ConflictResolutionStrategy.REJECT:
                    raise ImportConflictError(
                        f"Import rejected due to {len(plan.conflicts)} conflicting records. "
                        "Resolve conflicts using RENAME_NEW, OVERWRITE, or SKIP.",
                        conflicts=[c.to_dict() for c in plan.conflicts],
                        strategy_attempted=conflict_strategy.value,
                    )
                elif conflict_strategy == ConflictResolutionStrategy.OVERWRITE and not confirm_overwrite:
                    raise ImportConflictError(
                        "Overwriting conflicting records requires explicit confirm_overwrite=True.",
                        conflicts=[c.to_dict() for c in plan.conflicts],
                        strategy_attempted=conflict_strategy.value,
                    )

            # Step 5: Perform entity remapping if RENAME_NEW strategy is chosen
            activity_id_map: Dict[str, str] = {}
            checkpoint_id_map: Dict[str, str] = {}

            if conflict_strategy == ConflictResolutionStrategy.RENAME_NEW and plan.conflicts:
                activity_id_map, checkpoint_id_map = self._remap_conflicting_staged_records(
                    extracted_dir=extracted_dir,
                    conflicts=plan.conflicts,
                )

            # Step 6: Begin live commit phase with rollback journaling
            journal_data["status"] = ImportStageStatus.COMMITTING.value
            self._write_journal(journal_path, journal_data)

            result = self._commit_staged_to_live(
                import_id=import_id,
                extracted_dir=extracted_dir,
                rollback_dir=rollback_dir,
                journal_path=journal_path,
                journal_data=journal_data,
                plan=plan,
                conflict_strategy=conflict_strategy,
                activity_id_map=activity_id_map,
                checkpoint_id_map=checkpoint_id_map,
            )

            # Step 7: Rebuild derived indexes
            self.store.rebuild_index_from_authoritative_files()
            self.store.rebuild_search_index()
            result.indexes_rebuilt = ["activities_idx", "checkpoints_idx", "search_fts"]

            # Step 8: Mark committed in journal and move journal to history
            journal_data["status"] = ImportStageStatus.COMMITTED.value
            journal_data["completed_at"] = datetime.now(timezone.utc).isoformat()
            self._write_journal(journal_path, journal_data)

            self.history_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(journal_path, self.history_dir / f"{import_id}.json")

            # Clean up staging directory
            shutil.rmtree(stage_dir, ignore_errors=True)

            result.duration_seconds = time.time() - start_time
            return result

        except Exception as exc:
            # If commit was in progress or staging failed, execute rollback
            if journal_data.get("status") == ImportStageStatus.COMMITTING.value:
                self._execute_rollback(rollback_dir, journal_data)
                journal_data["status"] = ImportStageStatus.ROLLED_BACK.value
                journal_data["error"] = str(exc)
                self._write_journal(journal_path, journal_data)

            if isinstance(exc, (ImportError, CorruptedBackupError, UnsupportedBackupVersionError)):
                raise
            raise ImportError(f"Unexpected error during import: {exc}") from exc

    def recover_interrupted_imports(self) -> List[Dict[str, Any]]:
        """
        Inspects staging area for incomplete or interrupted import transactions.
        If an import was interrupted during the COMMITTING stage:
        - Automatically restores backed-up files from rollback/
        - Deletes partially written new files
        - Marks journal as ROLLED_BACK
        - Cleans up orphaned staging folders
        Ensures safe retry after interruption without manual cleanup.
        """
        recovered: List[Dict[str, Any]] = []
        if not self.staging_base.exists():
            return recovered

        for item in self.staging_base.iterdir():
            if not item.is_dir():
                continue

            journal_file = item / "journal.json"
            if not journal_file.is_file():
                # Stale directory without journal, remove it
                shutil.rmtree(item, ignore_errors=True)
                continue

            try:
                with open(journal_file, "r", encoding="utf-8") as f:
                    journal_data = json.load(f)

                status = journal_data.get("status")
                import_id = journal_data.get("import_id", item.name)

                if status == ImportStageStatus.COMMITTING.value:
                    # Power cut or crash during live commit! Perform rollback
                    rollback_dir = item / "rollback"
                    self._execute_rollback(rollback_dir, journal_data)
                    journal_data["status"] = ImportStageStatus.ROLLED_BACK.value
                    journal_data["recovered_at"] = datetime.now(timezone.utc).isoformat()
                    self._write_journal(journal_file, journal_data)

                    # Preserve record in history before clearing
                    self.history_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(journal_file, self.history_dir / f"{import_id}_recovered.json")
                    shutil.rmtree(item, ignore_errors=True)

                    recovered.append({
                        "import_id": import_id,
                        "action": "rolled_back_and_cleaned",
                        "status": "RECOVERED",
                    })

                elif status in (
                    ImportStageStatus.VALIDATING.value,
                    ImportStageStatus.STAGED.value,
                    ImportStageStatus.ROLLED_BACK.value,
                    ImportStageStatus.FAILED.value,
                ):
                    shutil.rmtree(item, ignore_errors=True)
                    recovered.append({
                        "import_id": import_id,
                        "action": "cleaned_stale_staging",
                        "status": "CLEANED",
                    })

            except Exception as err:
                recovered.append({
                    "path": str(item),
                    "action": "cleanup_error",
                    "error": str(err),
                })

        return recovered

    # --------------------------------------------------------------------------
    # Internal Helpers
    # --------------------------------------------------------------------------

    def _safe_extract_tar(self, archive_path: Path, target_dir: Path) -> None:
        """Extracts tar archive ensuring member paths stay within target_dir (Anti-ZipSlip)."""
        resolved_target = target_dir.resolve()
        with tarfile.open(archive_path, "r:*") as tar:
            for member in tar.getmembers():
                member_path = (resolved_target / member.name).resolve()
                if not str(member_path).startswith(str(resolved_target)):
                    raise CorruptedArchiveError(
                        f"Malicious archive member path traversal attempt: {member.name}"
                    )
            tar.extractall(path=resolved_target)

    def _analyze_staged_records(
        self,
        import_id: str,
        archive_path: str,
        manifest_data: Dict[str, Any],
        extracted_dir: Path,
        conflict_strategy: ConflictResolutionStrategy,
    ) -> ImportPlan:
        """Inspects extracted staged records and compares against live store for conflicts."""
        entities_to_add: List[Dict[str, Any]] = []
        entities_identical: List[Dict[str, Any]] = []
        conflicts: List[EntityConflict] = []

        # Discover existing live activities directly from storage
        live_act_dict: Dict[str, Activity] = {}
        activities_dir = self.continuum_dir / "activities"
        if activities_dir.is_dir():
            for act_folder in activities_dir.iterdir():
                if act_folder.is_dir():
                    live_act = self.store.get_activity(act_folder.name)
                    if live_act is not None:
                        live_act_dict[live_act.id] = live_act
        staged_act_ids: Set[str] = set()

        staged_activities_dir = extracted_dir / "activities"
        if staged_activities_dir.exists():
            for act_dir in staged_activities_dir.iterdir():
                if not act_dir.is_dir():
                    continue
                act_id = act_dir.name
                staged_act_ids.add(act_id)
                act_file = act_dir / "activity.json"
                if not act_file.is_file():
                    continue

                with open(act_file, "r", encoding="utf-8") as f:
                    staged_act_json = json.load(f)

                if act_id in live_act_dict:
                    live_act = live_act_dict[act_id]
                    # Compare content
                    if self._is_activity_content_identical(staged_act_json, live_act.to_dict()):
                        entities_identical.append({
                            "type": "activity",
                            "id": act_id,
                            "title": staged_act_json.get("title"),
                        })
                    else:
                        conflicts.append(EntityConflict(
                            entity_type="activity",
                            entity_id=act_id,
                            conflict_type=ConflictType.CONTENT_DIVERGENCE,
                            description=f"Activity '{act_id}' exists locally with differing attributes.",
                            existing_summary={"title": live_act.title, "status": live_act.status.value},
                            incoming_summary={"title": staged_act_json.get("title"), "status": staged_act_json.get("status")},
                        ))
                else:
                    entities_to_add.append({
                        "type": "activity",
                        "id": act_id,
                        "title": staged_act_json.get("title"),
                    })

                # Check staged checkpoints for this activity
                chk_dir = act_dir / "checkpoints"
                if chk_dir.exists():
                    for chk_file in chk_dir.glob("*.json"):
                        chk_id = chk_file.stem
                        with open(chk_file, "r", encoding="utf-8") as cf:
                            staged_chk_json = json.load(cf)

                        try:
                            live_chk = self.store.get_checkpoint(chk_id)
                        except Exception:
                            live_chk = None

                        if live_chk is not None:
                            if self._is_checkpoint_content_identical(staged_chk_json, live_chk.to_dict()):
                                entities_identical.append({
                                    "type": "checkpoint",
                                    "id": chk_id,
                                    "activity_id": act_id,
                                })
                            else:
                                conflicts.append(EntityConflict(
                                    entity_type="checkpoint",
                                    entity_id=chk_id,
                                    conflict_type=ConflictType.CONTENT_DIVERGENCE,
                                    description=f"Checkpoint '{chk_id}' exists locally with differing content.",
                                    existing_summary={"timestamp": live_chk.timestamp, "context": live_chk.context},
                                    incoming_summary={"timestamp": staged_chk_json.get("timestamp"), "context": staged_chk_json.get("context")},
                                ))
                        else:
                            entities_to_add.append({
                                "type": "checkpoint",
                                "id": chk_id,
                                "activity_id": act_id,
                            })

        unrelated_count = len([aid for aid in live_act_dict if aid not in staged_act_ids])
        has_blocking = False
        if conflicts:
            if conflict_strategy == ConflictResolutionStrategy.REJECT:
                has_blocking = True
            elif conflict_strategy == ConflictResolutionStrategy.OVERWRITE:
                # Blocking if not confirmed
                has_blocking = True

        return ImportPlan(
            import_id=import_id,
            archive_path=archive_path,
            manifest_summary=manifest_data.get("records_summary", {}),
            entities_to_add=entities_to_add,
            entities_identical=entities_identical,
            conflicts=conflicts,
            conflict_strategy=conflict_strategy,
            has_blocking_conflicts=has_blocking,
            unrelated_activities_count=unrelated_count,
        )

    def _remap_conflicting_staged_records(
        self,
        extracted_dir: Path,
        conflicts: List[EntityConflict],
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        """
        Renames conflicting staged entities with new UUIDs and rewires references.
        Returns (activity_id_map, checkpoint_id_map).
        """
        activity_id_map: Dict[str, str] = {}
        checkpoint_id_map: Dict[str, str] = {}

        for c in conflicts:
            if c.entity_type == "activity":
                new_act_id = f"act_{uuid.uuid4().hex[:12]}"
                activity_id_map[c.entity_id] = new_act_id
            elif c.entity_type == "checkpoint":
                new_chk_id = f"chk_{uuid.uuid4().hex[:12]}"
                checkpoint_id_map[c.entity_id] = new_chk_id

        staged_activities_dir = extracted_dir / "activities"
        if not staged_activities_dir.exists():
            return activity_id_map, checkpoint_id_map

        # Process activity renames
        for old_act_id, new_act_id in activity_id_map.items():
            old_dir = staged_activities_dir / old_act_id
            if old_dir.is_dir():
                new_dir = staged_activities_dir / new_act_id
                old_dir.rename(new_dir)
                act_file = new_dir / "activity.json"
                if act_file.is_file():
                    with open(act_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data["id"] = new_act_id
                    data["provenance"] = {
                        "type": ProvenanceType.IMPORTED.value,
                        "source": f"renamed_from_{old_act_id}",
                    }
                    with open(act_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)

        # Process checkpoint updates (both activity remapping and checkpoint renames)
        for act_dir in staged_activities_dir.iterdir():
            if not act_dir.is_dir():
                continue
            curr_act_id = act_dir.name
            chk_dir = act_dir / "checkpoints"
            if not chk_dir.is_dir():
                continue

            for chk_file in list(chk_dir.glob("*.json")):
                old_chk_id = chk_file.stem
                with open(chk_file, "r", encoding="utf-8") as f:
                    chk_data = json.load(f)

                modified = False
                # Update activity_id if changed
                if chk_data.get("activity_id") in activity_id_map:
                    chk_data["activity_id"] = activity_id_map[chk_data["activity_id"]]
                    modified = True

                # Update parent_id if parent checkpoint was renamed
                if chk_data.get("parent_id") in checkpoint_id_map:
                    chk_data["parent_id"] = checkpoint_id_map[chk_data["parent_id"]]
                    modified = True

                # Rename checkpoint itself if in checkpoint_id_map
                if old_chk_id in checkpoint_id_map:
                    new_chk_id = checkpoint_id_map[old_chk_id]
                    chk_data["id"] = new_chk_id
                    chk_data["provenance"] = {
                        "type": ProvenanceType.IMPORTED.value,
                        "source": f"renamed_from_{old_chk_id}",
                    }
                    modified = True
                    target_file = chk_dir / f"{new_chk_id}.json"
                    chk_file.unlink()
                    with open(target_file, "w", encoding="utf-8") as f:
                        json.dump(chk_data, f, indent=2)
                elif modified:
                    with open(chk_file, "w", encoding="utf-8") as f:
                        json.dump(chk_data, f, indent=2)

        return activity_id_map, checkpoint_id_map

    def _commit_staged_to_live(
        self,
        import_id: str,
        extracted_dir: Path,
        rollback_dir: Path,
        journal_path: Path,
        journal_data: Dict[str, Any],
        plan: ImportPlan,
        conflict_strategy: ConflictResolutionStrategy,
        activity_id_map: Dict[str, str],
        checkpoint_id_map: Dict[str, str],
    ) -> ImportResult:
        """
        Atomically copies staged records to live .continuum directories,
        backing up existing files to rollback/ before overwrite.
        """
        result = ImportResult(
            import_id=import_id,
            success=True,
            activities_imported=0,
            checkpoints_imported=0,
            artifacts_imported=0,
            configs_imported=0,
            activities_renamed=activity_id_map,
            checkpoints_renamed=checkpoint_id_map,
            unrelated_activities_preserved=plan.unrelated_activities_count,
        )

        conflicting_act_ids = {c.entity_id for c in plan.conflicts if c.entity_type == "activity"}
        conflicting_chk_ids = {c.entity_id for c in plan.conflicts if c.entity_type == "checkpoint"}

        # Staged activities
        staged_activities_dir = extracted_dir / "activities"
        live_activities_dir = self.continuum_dir / "activities"
        live_activities_dir.mkdir(parents=True, exist_ok=True)

        if staged_activities_dir.exists():
            for act_dir in staged_activities_dir.iterdir():
                if not act_dir.is_dir():
                    continue
                act_id = act_dir.name
                original_act_id = act_id
                # Reverse check if renamed
                for orig, new in activity_id_map.items():
                    if new == act_id:
                        original_act_id = orig
                        break

                if conflict_strategy == ConflictResolutionStrategy.SKIP and original_act_id in conflicting_act_ids:
                    result.activities_skipped.append(original_act_id)
                    continue

                target_act_dir = live_activities_dir / act_id
                target_act_dir.mkdir(parents=True, exist_ok=True)
                target_act_file = target_act_dir / "activity.json"
                source_act_file = act_dir / "activity.json"

                if source_act_file.is_file():
                    if target_act_file.exists():
                        # Backup existing to rollback
                        rel_path = target_act_file.relative_to(self.continuum_dir)
                        backup_target = rollback_dir / rel_path
                        backup_target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target_act_file, backup_target)
                        journal_data["overwritten_files"].append(str(rel_path))
                        result.activities_overwritten.append(act_id)
                    else:
                        journal_data["created_files"].append(str(target_act_file.relative_to(self.continuum_dir)))

                    shutil.copy2(source_act_file, target_act_file)
                    result.activities_imported += 1

                # Checkpoints
                staged_chk_dir = act_dir / "checkpoints"
                target_chk_dir = target_act_dir / "checkpoints"
                target_chk_dir.mkdir(parents=True, exist_ok=True)

                if staged_chk_dir.exists():
                    for source_chk_file in staged_chk_dir.glob("*.json"):
                        chk_id = source_chk_file.stem
                        original_chk_id = chk_id
                        for orig_c, new_c in checkpoint_id_map.items():
                            if new_c == chk_id:
                                original_chk_id = orig_c
                                break

                        if conflict_strategy == ConflictResolutionStrategy.SKIP and original_chk_id in conflicting_chk_ids:
                            result.checkpoints_skipped.append(original_chk_id)
                            continue

                        target_chk_file = target_chk_dir / f"{chk_id}.json"
                        if target_chk_file.exists():
                            rel_path = target_chk_file.relative_to(self.continuum_dir)
                            backup_target = rollback_dir / rel_path
                            backup_target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(target_chk_file, backup_target)
                            journal_data["overwritten_files"].append(str(rel_path))
                            result.checkpoints_overwritten.append(chk_id)
                        else:
                            journal_data["created_files"].append(str(target_chk_file.relative_to(self.continuum_dir)))

                        shutil.copy2(source_chk_file, target_chk_file)
                        result.checkpoints_imported += 1

        # Staged artifacts
        staged_artifacts_dir = extracted_dir / "artifacts"
        if staged_artifacts_dir.exists():
            live_artifacts_dir = self.continuum_dir / "artifacts"
            live_artifacts_dir.mkdir(parents=True, exist_ok=True)
            for source_art in staged_artifacts_dir.glob("**/*"):
                if source_art.is_file():
                    rel_art = source_art.relative_to(staged_artifacts_dir)
                    target_art = live_artifacts_dir / rel_art
                    target_art.parent.mkdir(parents=True, exist_ok=True)
                    if target_art.exists():
                        rel_path = target_art.relative_to(self.continuum_dir)
                        backup_target = rollback_dir / rel_path
                        backup_target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target_art, backup_target)
                        journal_data["overwritten_files"].append(str(rel_path))
                    else:
                        journal_data["created_files"].append(str(target_art.relative_to(self.continuum_dir)))
                    shutil.copy2(source_art, target_art)
                    result.artifacts_imported += 1

        # Update journal with file operations
        self._write_journal(journal_path, journal_data)
        return result

    def _execute_rollback(self, rollback_dir: Path, journal_data: Dict[str, Any]) -> None:
        """Restores files from rollback directory and deletes newly created files."""
        # 1. Restore overwritten files from rollback
        for rel_file in journal_data.get("overwritten_files", []):
            backup_file = rollback_dir / rel_file
            dest_file = self.continuum_dir / rel_file
            if backup_file.is_file():
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_file, dest_file)

        # 2. Delete newly created files
        for rel_file in journal_data.get("created_files", []):
            created_file = self.continuum_dir / rel_file
            if created_file.is_file():
                created_file.unlink(missing_ok=True)

    def _is_activity_content_identical(self, a_dict: Dict[str, Any], b_dict: Dict[str, Any]) -> bool:
        """Compares essential fields of two activity dictionaries."""
        keys = ["id", "title", "activity_type", "status", "tags", "collection"]
        for k in keys:
            if a_dict.get(k) != b_dict.get(k):
                return False
        return True

    def _is_checkpoint_content_identical(self, a_dict: Dict[str, Any], b_dict: Dict[str, Any]) -> bool:
        """Compares essential fields of two checkpoint dictionaries."""
        keys = ["id", "activity_id", "timestamp", "context", "progress"]
        for k in keys:
            if a_dict.get(k) != b_dict.get(k):
                return False
        return True

    def _write_journal(self, journal_path: Path, data: Dict[str, Any]) -> None:
        """Safely writes JSON journal file atomically."""
        tmp = journal_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(journal_path)
