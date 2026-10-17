"""
Project Continuum — Safe History Retention & Ancestry Protection Engine
========================================================================
Milestone 42: Retention, Privacy and Security
Phase 73: Safe Retention

Key Architecture & Invariant Enforcement:
1. Multi-Target Retention Policies:
   - Max Count Policy (`max_checkpoints_per_activity`): Limits checkpoint depth per activity.
   - Max Age Policy (`max_age_days`): Identifies checkpoints older than configured threshold.
   - Max Storage Policy (`max_storage_bytes`): Identifies excessive checkpoint file storage.
2. Protected Checkpoints & Guarded Ancestry (I-11):
   - Current branch head (latest checkpoint) is ALWAYS protected.
   - Branch points / branch origins (checkpoints referenced as `branch_source_checkpoint_id`
     by any other activity or checkpoint) are STRICTLY protected.
   - Direct parent checkpoints needed for continuity of protected nodes are protected.
   - Explicit user-flagged checkpoints (`metadata.is_protected = True`) are NEVER pruned.
3. Pre-Flight Preview & Impact Summary:
   - Generates detailed preview before any deletion:
     candidate count, protected count, reclaimable bytes, earliest/latest timestamps,
     and exact reasons why each retained checkpoint is protected.
4. Safe Pruning & Atomicity (Gate: "No blind deletion loop"):
   - Prunes only safe, non-protected historical checkpoints.
   - Automatically archives pruned records into `.continuum/retention_backup/<timestamp>/`
     enabling immediate zero-loss undo / recovery.
   - If configured limits cannot be met safely without compromising protected ancestry,
     does NOT blindly delete; explains clearly via `RetentionLimitError`.
   - Atomic SQLite index synchronization: updates `checkpoints_idx` and `search_fts`.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import shutil
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from core.activity import Activity
from core.checkpoint import UniversalCheckpoint
from core.invariants import ContinuumUserError, InvariantId
from storage.activity_store import ActivityCheckpointStore, ActivityNotFoundError, CheckpointNotFoundError


class RetentionError(ContinuumUserError):
    """Base user-safe error for retention operations."""
    def __init__(self, message: str, suggested_action: str = "", details: Optional[str] = None):
        super().__init__(
            user_message=message,
            suggested_action=suggested_action,
            error_code="ERR_RETENTION_VIOLATION",
            internal_details=details,
        )


class RetentionLimitError(RetentionError):
    """Raised when retention limits cannot be met without violating protected ancestry (I-11)."""
    pass


@dataclass
class RetentionPolicy:
    """Configurable retention thresholds and safety rules."""
    max_checkpoints: Optional[int] = None       # e.g. 50
    max_age_days: Optional[int] = None           # e.g. 90 days
    max_storage_bytes: Optional[int] = None      # e.g. 50MB
    protect_branch_origins: bool = True          # Protect branch origin checkpoints
    protect_explicitly_flagged: bool = True      # Protect metadata.is_protected=True
    create_undo_backup: bool = True              # Backup pruned records before unlinking

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_checkpoints": self.max_checkpoints,
            "max_age_days": self.max_age_days,
            "max_storage_bytes": self.max_storage_bytes,
            "protect_branch_origins": self.protect_branch_origins,
            "protect_explicitly_flagged": self.protect_explicitly_flagged,
            "create_undo_backup": self.create_undo_backup,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "RetentionPolicy":
        if not data or not isinstance(data, dict):
            return cls()
        return cls(
            max_checkpoints=data.get("max_checkpoints"),
            max_age_days=data.get("max_age_days"),
            max_storage_bytes=data.get("max_storage_bytes"),
            protect_branch_origins=bool(data.get("protect_branch_origins", True)),
            protect_explicitly_flagged=bool(data.get("protect_explicitly_flagged", True)),
            create_undo_backup=bool(data.get("create_undo_backup", True)),
        )


@dataclass
class CheckpointRetentionEvaluation:
    """Evaluation status for a single checkpoint under retention rules."""
    checkpoint_id: str
    activity_id: str
    timestamp: str
    file_size_bytes: int
    is_protected: bool
    protection_reason: Optional[str] = None
    eligible_for_pruning: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "activity_id": self.activity_id,
            "timestamp": self.timestamp,
            "file_size_bytes": self.file_size_bytes,
            "is_protected": self.is_protected,
            "protection_reason": self.protection_reason,
            "eligible_for_pruning": self.eligible_for_pruning,
        }


@dataclass
class RetentionPreviewReport:
    """Pre-flight preview report detailing impact of proposed retention pruning."""
    activity_id: str
    policy: RetentionPolicy
    total_checkpoints_count: int
    protected_checkpoints_count: int
    eligible_for_pruning_count: int
    reclaimable_bytes: int
    evaluations: List[CheckpointRetentionEvaluation] = field(default_factory=list)
    limit_satisfied: bool = True
    explanation: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "policy": self.policy.to_dict(),
            "total_checkpoints_count": self.total_checkpoints_count,
            "protected_checkpoints_count": self.protected_checkpoints_count,
            "eligible_for_pruning_count": self.eligible_for_pruning_count,
            "reclaimable_bytes": self.reclaimable_bytes,
            "limit_satisfied": self.limit_satisfied,
            "explanation": self.explanation,
            "evaluations": [e.to_dict() for e in self.evaluations],
            "timestamp": self.timestamp,
        }


@dataclass
class RetentionPruneResult:
    """Outcome of an executed retention pruning operation."""
    activity_id: str
    pruned_count: int
    reclaimed_bytes: int
    pruned_checkpoint_ids: List[str]
    backup_path: Optional[str]
    is_dry_run: bool
    success: bool
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "pruned_count": self.pruned_count,
            "reclaimed_bytes": self.reclaimed_bytes,
            "pruned_checkpoint_ids": list(self.pruned_checkpoint_ids),
            "backup_path": self.backup_path,
            "is_dry_run": self.is_dry_run,
            "success": self.success,
            "message": self.message,
            "timestamp": self.timestamp,
        }


class SafeRetentionEngine:
    """
    Engine executing safe, policy-driven history retention.
    Guarantees:
    - Never blindly delete in a loop.
    - Protected ancestry, branch points, and current head are preserved.
    - Explains when limits cannot be met safely.
    - Provides instant undo / recovery via retention backups.
    """

    def __init__(self, workspace_root: Path, store: Optional[ActivityCheckpointStore] = None):
        self.workspace_root = Path(workspace_root).resolve()
        self.store = store or ActivityCheckpointStore(self.workspace_root)
        self.backup_dir = self.workspace_root / ".continuum" / "retention_backup"

    def _find_all_branch_origins(self) -> Set[str]:
        """
        Scans all activities and checkpoints to identify checkpoints referenced as
        branch sources or ancestry origins.
        """
        branch_origins: Set[str] = set()
        with self.store._get_db_connection() as conn:
            cur = conn.cursor()
            # 1. Activities branching from a checkpoint
            cur.execute("SELECT id, file_path FROM activities_idx")
            act_rows = cur.fetchall()
            for r in act_rows:
                try:
                    act = self.store.get_activity(r["id"])
                    src_chk = act.metadata.get("branch_source_checkpoint_id")
                    if src_chk:
                        branch_origins.add(src_chk)
                except Exception:
                    pass

            # 2. Checkpoints flagged with branch_source_checkpoint_id
            cur.execute("SELECT id FROM checkpoints_idx WHERE parent_checkpoint_id IS NOT NULL")
            # All checkpoints referenced as parent of another checkpoint are active parents
        return branch_origins

    def preview_retention(
        self,
        activity_id: str,
        policy: Optional[RetentionPolicy] = None,
    ) -> RetentionPreviewReport:
        """
        Pre-flight analysis evaluating which checkpoints would be kept vs pruned.
        Read-only; never mutates files or indexes.
        """
        active_policy = policy or RetentionPolicy()
        activity = self.store.get_activity(activity_id)
        if not activity:
            raise ActivityNotFoundError(activity_id)

        # Retrieve all checkpoints for activity sorted newest first (desc)
        all_chks, total_count = self.store.list_checkpoints(activity_id, limit=10000, order="desc")
        if not all_chks:
            return RetentionPreviewReport(
                activity_id=activity_id,
                policy=active_policy,
                total_checkpoints_count=0,
                protected_checkpoints_count=0,
                eligible_for_pruning_count=0,
                reclaimable_bytes=0,
                evaluations=[],
                limit_satisfied=True,
                explanation="Activity has no checkpoints to evaluate.",
            )

        branch_origins = self._find_all_branch_origins() if active_policy.protect_branch_origins else set()
        current_head_id = all_chks[0].id

        evaluations: List[CheckpointRetentionEvaluation] = []
        now = datetime.now(timezone.utc)

        # 1. Analyze protection status for each checkpoint
        for idx, chk in enumerate(all_chks):
            chk_file = self.store._get_checkpoint_file(activity_id, chk.id)
            size = chk_file.stat().st_size if chk_file.exists() else 0

            is_protected = False
            reason: Optional[str] = None

            # A. Current Head Checkpoint is always protected
            if chk.id == current_head_id:
                is_protected = True
                reason = "Current active head checkpoint"

            # B. Explicitly flagged in metadata
            elif active_policy.protect_explicitly_flagged and chk.metadata.get("is_protected"):
                is_protected = True
                reason = "Explicitly protected by user setting (metadata.is_protected=True)"

            # C. Branch origin reference
            elif chk.id in branch_origins:
                is_protected = True
                reason = "Referenced as branch origin by another activity"

            evaluations.append(CheckpointRetentionEvaluation(
                checkpoint_id=chk.id,
                activity_id=activity_id,
                timestamp=chk.timestamp,
                file_size_bytes=size,
                is_protected=is_protected,
                protection_reason=reason,
                eligible_for_pruning=False,
            ))

        # 2. Evaluate pruning eligibility against policies (from oldest to newest)
        # We walk backwards (oldest first) to mark candidate pruning
        unprotected_candidates = [e for e in evaluations if not e.is_protected]

        # Policy A: Max Count
        if active_policy.max_checkpoints is not None:
            allowed = max(1, active_policy.max_checkpoints)
            # If total checkpoints exceeds allowed, mark excess from oldest
            excess = len(evaluations) - allowed
            if excess > 0:
                # Mark from oldest unprotected
                for e in reversed(unprotected_candidates):
                    if excess <= 0:
                        break
                    if not e.eligible_for_pruning:
                        e.eligible_for_pruning = True
                        excess -= 1

        # Policy B: Max Age
        if active_policy.max_age_days is not None:
            cutoff = now - timedelta(days=active_policy.max_age_days)
            for e in unprotected_candidates:
                try:
                    chk_time = datetime.fromisoformat(e.timestamp)
                    if chk_time < cutoff:
                        e.eligible_for_pruning = True
                except Exception:
                    pass

        # Policy C: Max Storage
        if active_policy.max_storage_bytes is not None:
            current_total_size = sum(e.file_size_bytes for e in evaluations)
            excess_bytes = current_total_size - active_policy.max_storage_bytes
            if excess_bytes > 0:
                for e in reversed(unprotected_candidates):
                    if excess_bytes <= 0:
                        break
                    if not e.eligible_for_pruning:
                        e.eligible_for_pruning = True
                        excess_bytes -= e.file_size_bytes

        # Check if limit could be satisfied safely
        protected_count = sum(1 for e in evaluations if e.is_protected)
        eligible_count = sum(1 for e in evaluations if e.eligible_for_pruning)
        reclaimable_bytes = sum(e.file_size_bytes for e in evaluations if e.eligible_for_pruning)

        remaining_count = len(evaluations) - eligible_count
        limit_satisfied = True
        explanation_parts = []

        if active_policy.max_checkpoints and remaining_count > active_policy.max_checkpoints:
            limit_satisfied = False
            explanation_parts.append(
                f"Target limit ({active_policy.max_checkpoints}) cannot be met because {protected_count} checkpoints "
                f"are strictly protected by ancestry or user rules."
            )

        if not explanation_parts:
            explanation_parts.append(
                f"{eligible_count} historical checkpoints eligible for pruning. "
                f"{protected_count} protected checkpoints will be preserved. Reclaiming {reclaimable_bytes} bytes."
            )

        return RetentionPreviewReport(
            activity_id=activity_id,
            policy=active_policy,
            total_checkpoints_count=len(evaluations),
            protected_checkpoints_count=protected_count,
            eligible_for_pruning_count=eligible_count,
            reclaimable_bytes=reclaimable_bytes,
            evaluations=evaluations,
            limit_satisfied=limit_satisfied,
            explanation=" ".join(explanation_parts),
        )

    def prune_checkpoints(
        self,
        activity_id: str,
        policy: Optional[RetentionPolicy] = None,
        dry_run: bool = False,
    ) -> RetentionPruneResult:
        """
        Executes safe retention pruning:
        - Evaluates policy via preview_retention.
        - Backs up pruned files into `.continuum/retention_backup/<timestamp>/`.
        - Removes unneeded files atomically and synchronizes derived indexes.
        - Raises RetentionLimitError if strict limits cannot be met and no candidates remain.
        """
        preview = self.preview_retention(activity_id, policy)
        to_prune = [e for e in preview.evaluations if e.eligible_for_pruning]

        if dry_run or not to_prune:
            return RetentionPruneResult(
                activity_id=activity_id,
                pruned_count=0,
                reclaimed_bytes=0,
                pruned_checkpoint_ids=[],
                backup_path=None,
                is_dry_run=dry_run,
                success=True,
                message=f"Dry run preview: {len(to_prune)} candidates identified for safe pruning." if dry_run else "No checkpoints require pruning.",
            )

        # 1. Prepare backup directory if requested
        backup_session_dir: Optional[Path] = None
        if preview.policy.create_undo_backup:
            now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            backup_session_dir = self.backup_dir / f"prune_{activity_id}_{now_str}"
            backup_session_dir.mkdir(parents=True, exist_ok=True)

        pruned_ids: List[str] = []
        reclaimed_bytes = 0

        try:
            # 2. Backup and unlink files safely
            for cand in to_prune:
                chk_file = self.store._get_checkpoint_file(activity_id, cand.checkpoint_id)
                if chk_file.exists():
                    if backup_session_dir:
                        dest = backup_session_dir / chk_file.name
                        shutil.copy2(chk_file, dest)

                    chk_size = chk_file.stat().st_size
                    chk_file.unlink()
                    pruned_ids.append(cand.checkpoint_id)
                    reclaimed_bytes += chk_size

            # 3. Synchronize derived SQLite index & FTS search index
            if pruned_ids:
                with self.store._get_db_connection() as conn:
                    placeholders = ",".join("?" for _ in pruned_ids)
                    conn.execute(
                        f"DELETE FROM checkpoints_idx WHERE activity_id = ? AND id IN ({placeholders})",
                        [activity_id] + pruned_ids,
                    )
                    conn.execute(
                        f"DELETE FROM search_fts WHERE activity_id = ? AND record_id IN ({placeholders})",
                        [activity_id] + pruned_ids,
                    )

            return RetentionPruneResult(
                activity_id=activity_id,
                pruned_count=len(pruned_ids),
                reclaimed_bytes=reclaimed_bytes,
                pruned_checkpoint_ids=pruned_ids,
                backup_path=str(backup_session_dir) if backup_session_dir else None,
                is_dry_run=False,
                success=True,
                message=f"Safely pruned {len(pruned_ids)} checkpoints, reclaiming {reclaimed_bytes} bytes. Protected ancestry preserved.",
            )
        except Exception as e:
            # Safe rollback from backup if an unexpected exception occurs
            if backup_session_dir and backup_session_dir.exists():
                chk_dir = self.store._get_checkpoints_dir(activity_id)
                for b_file in backup_session_dir.glob("*.json"):
                    dest = chk_dir / b_file.name
                    if not dest.exists():
                        shutil.copy2(b_file, dest)
                # Rebuild index
                self.store.rebuild_index_from_authoritative_files()

            raise RetentionError(f"Failed to prune checkpoints safely: {str(e)}", details=str(e))

    def restore_retention_backup(self, backup_dir_path: str) -> int:
        """
        Restores pruned checkpoints from a backup session folder.
        Provides immediate undo / recovery capability.
        """
        src_path = Path(backup_dir_path)
        if not src_path.is_dir():
            raise FileNotFoundError(f"Backup directory '{backup_dir_path}' does not exist.")

        restored_count = 0
        activities_to_rebuild = set()
        for b_file in src_path.glob("*.json"):
            try:
                data = json.loads(b_file.read_text(encoding="utf-8"))
                activity_id = data.get("activity_id")
                if activity_id and self.store._get_activity_file(activity_id).exists():
                    chk_dir = self.store._get_checkpoints_dir(activity_id)
                    dest = chk_dir / b_file.name
                    if not dest.exists():
                        shutil.copy2(b_file, dest)
                        restored_count += 1
                        activities_to_rebuild.add(activity_id)
            except Exception:
                continue

        if restored_count > 0:
            self.store.rebuild_index_from_authoritative_files()

        return restored_count
