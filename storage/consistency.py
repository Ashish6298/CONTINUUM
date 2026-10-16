"""
Project Continuum — Storage Consistency Verification & Safe Recovery Engine
============================================================================
Milestone 37: Durable Storage and Migration
Phase 58: Consistency and Recovery

Implements:
1. Detection of:
   - Orphaned checkpoints (checkpoints without owning activity).
   - Missing activities (activity directories lacking valid activity.json).
   - Invalid branch / parent references (broken ancestry links).
   - Malformed records (unparseable JSON or invalid schema).
   - Derived-index mismatches (discrepancy between authoritative files and SQLite).
   - Stale temporary files (interrupted in-flight writes).
2. Explicit, non-destructive repair:
   - Zero silent data loss: malformed files are quarantined, never deleted.
   - Reconstructs missing activity headers preserving all checkpoint histories.
   - Preserves broken reference IDs in metadata before unlinking.
   - Deterministic index rebuilds restoring SQLite B-Tree and full-text indexes (I-06).
3. Repeatable and idempotent audit & repair guarantees (I-14, I-20).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Set, Tuple

from core.activity import Activity, ActivityStatus, ActivityType
from core.checkpoint import UniversalCheckpoint
from storage.activity_store import ActivityCheckpointStore, ActivityNotFoundError, CheckpointNotFoundError


class ConsistencyIssueType(str, Enum):
    """Categorization of detected storage consistency anomalies."""
    ORPHANED_CHECKPOINT = "orphaned_checkpoint"
    MISSING_ACTIVITY_RECORD = "missing_activity_record"
    INVALID_BRANCH_REFERENCE = "invalid_branch_reference"
    MALFORMED_RECORD = "malformed_record"
    DERIVED_INDEX_MISMATCH = "derived_index_mismatch"
    STALE_TEMPORARY_FILE = "stale_temporary_file"


@dataclass
class ConsistencyIssue:
    """Formal diagnostic record of a single detected consistency anomaly."""
    issue_type: ConsistencyIssueType
    file_path: str
    entity_id: Optional[str]
    activity_id: Optional[str]
    description: str
    remediable: bool
    suggested_action: str
    repaired: bool = False
    repair_details: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_type": self.issue_type.value,
            "file_path": self.file_path,
            "entity_id": self.entity_id,
            "activity_id": self.activity_id,
            "description": self.description,
            "remediable": self.remediable,
            "suggested_action": self.suggested_action,
            "repaired": self.repaired,
            "repair_details": self.repair_details,
        }


@dataclass
class ConsistencyAuditReport:
    """Authoritative outcome of a non-mutating storage consistency audit."""
    workspace_root: str
    audited_at: str
    total_activities_found: int
    total_checkpoints_found: int
    issues_found: List[ConsistencyIssue] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return len(self.issues_found) == 0

    @property
    def issues_by_type(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for issue in self.issues_found:
            counts[issue.issue_type.value] = counts.get(issue.issue_type.value, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workspace_root": self.workspace_root,
            "audited_at": self.audited_at,
            "total_activities_found": self.total_activities_found,
            "total_checkpoints_found": self.total_checkpoints_found,
            "is_clean": self.is_clean,
            "issues_count": len(self.issues_found),
            "issues_by_type": self.issues_by_type,
            "issues": [i.to_dict() for i in self.issues_found],
        }


@dataclass
class ConsistencyRepairResult:
    """Authoritative outcome of an explicit consistency repair execution."""
    workspace_root: str
    repaired_at: str
    is_dry_run: bool
    issues_detected: int
    issues_repaired: int
    quarantined_files: List[str] = field(default_factory=list)
    rebuilt_index_records: int = 0
    is_clean_post_repair: bool = True
    details: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workspace_root": self.workspace_root,
            "repaired_at": self.repaired_at,
            "is_dry_run": self.is_dry_run,
            "issues_detected": self.issues_detected,
            "issues_repaired": self.issues_repaired,
            "quarantined_files": list(self.quarantined_files),
            "rebuilt_index_records": self.rebuilt_index_records,
            "is_clean_post_repair": self.is_clean_post_repair,
            "details": self.details,
        }


class StorageConsistencyEngine:
    """
    Diagnostic and safe recovery engine for Continuum Activity & Checkpoint storage.
    Enforces Invariants:
    - Never silently discard data.
    - Explicit, repeatable repair operations.
    - Full authoritative file preservation.
    """

    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root).resolve()
        self.continuum_dir = self.workspace_root / ".continuum"
        self.activities_dir = self.continuum_dir / "activities"
        self.quarantine_dir = self.continuum_dir / "quarantine"
        self.db_path = self.continuum_dir / "index.db"
        self.store = ActivityCheckpointStore(str(self.workspace_root))

    def audit(self) -> ConsistencyAuditReport:
        """
        Executes a strictly read-only audit of all authoritative partitions and derived indexes.
        Identifies orphaned checkpoints, missing activities, broken ancestry,
        malformed JSON, index discrepancies, and stale temporary files.
        """
        issues: List[ConsistencyIssue] = []
        total_activities = 0
        total_checkpoints = 0

        if not self.activities_dir.exists():
            return ConsistencyAuditReport(
                workspace_root=str(self.workspace_root),
                audited_at=datetime.now(timezone.utc).isoformat(),
                total_activities_found=0,
                total_checkpoints_found=0,
                issues_found=[],
            )

        known_activity_ids: Set[str] = set()
        known_checkpoint_ids: Set[str] = set()
        checkpoints_to_validate: List[Tuple[Path, str, str]] = []  # (path, act_id, chk_id)

        # 1. Scan activity directories
        for act_dir in sorted(self.activities_dir.iterdir()):
            if not act_dir.is_dir():
                continue

            act_id = act_dir.name
            act_file = act_dir / "activity.json"
            chk_dir = act_dir / "checkpoints"

            # Check for stale tmp files in activity dir
            for tmp in act_dir.glob("*.tmp*"):
                issues.append(
                    ConsistencyIssue(
                        issue_type=ConsistencyIssueType.STALE_TEMPORARY_FILE,
                        file_path=str(tmp),
                        entity_id=None,
                        activity_id=act_id,
                        description=f"Abandoned temporary file: {tmp.name}",
                        remediable=True,
                        suggested_action="Remove stale temporary file.",
                    )
                )

            # Check activity.json
            if not act_file.exists():
                # Directory exists, maybe has checkpoints, but no activity.json
                has_checkpoints = chk_dir.exists() and any(chk_dir.glob("*.json"))
                issues.append(
                    ConsistencyIssue(
                        issue_type=ConsistencyIssueType.MISSING_ACTIVITY_RECORD,
                        file_path=str(act_file),
                        entity_id=act_id,
                        activity_id=act_id,
                        description=f"Activity directory '{act_id}' exists but 'activity.json' is missing (contains checkpoints: {has_checkpoints}).",
                        remediable=True,
                        suggested_action="Reconstruct activity.json header preserving checkpoints.",
                    )
                )
            else:
                # Validate activity.json parseability and schema
                try:
                    with open(act_file, "r", encoding="utf-8") as f:
                        act_data = json.load(f)
                    act = Activity.from_dict(act_data)
                    known_activity_ids.add(act.id)
                    total_activities += 1
                except Exception as e:
                    issues.append(
                        ConsistencyIssue(
                            issue_type=ConsistencyIssueType.MALFORMED_RECORD,
                            file_path=str(act_file),
                            entity_id=act_id,
                            activity_id=act_id,
                            description=f"Malformed activity record: {e}",
                            remediable=True,
                            suggested_action="Quarantine corrupted activity file and reconstruct default header.",
                        )
                    )

            # 2. Scan checkpoints directory for this activity
            if chk_dir.exists() and chk_dir.is_dir():
                for tmp in chk_dir.glob("*.tmp*"):
                    issues.append(
                        ConsistencyIssue(
                            issue_type=ConsistencyIssueType.STALE_TEMPORARY_FILE,
                            file_path=str(tmp),
                            entity_id=None,
                            activity_id=act_id,
                            description=f"Abandoned checkpoint temporary file: {tmp.name}",
                            remediable=True,
                            suggested_action="Remove stale temporary file.",
                        )
                    )

                for chk_file in sorted(chk_dir.glob("*.json")):
                    if chk_file.name.endswith(".tmp") or ".tmp_" in chk_file.name:
                        continue

                    chk_id = chk_file.stem
                    try:
                        with open(chk_file, "r", encoding="utf-8") as f:
                            chk_data = json.load(f)
                        chk = UniversalCheckpoint.from_dict(chk_data)
                        known_checkpoint_ids.add(chk.id)
                        total_checkpoints += 1
                        checkpoints_to_validate.append((chk_file, act_id, chk.id))

                        # Check for orphaned checkpoint (activity_id mismatch)
                        if chk.activity_id != act_id:
                            issues.append(
                                ConsistencyIssue(
                                    issue_type=ConsistencyIssueType.ORPHANED_CHECKPOINT,
                                    file_path=str(chk_file),
                                    entity_id=chk.id,
                                    activity_id=chk.activity_id,
                                    description=f"Checkpoint '{chk.id}' declares activity_id='{chk.activity_id}' but is located in '{act_id}'.",
                                    remediable=True,
                                    suggested_action="Reattach checkpoint to its declared activity or harmonize location.",
                                )
                            )
                    except Exception as e:
                        issues.append(
                            ConsistencyIssue(
                                issue_type=ConsistencyIssueType.MALFORMED_RECORD,
                                file_path=str(chk_file),
                                entity_id=chk_id,
                                activity_id=act_id,
                                description=f"Malformed checkpoint file '{chk_file.name}': {e}",
                                remediable=True,
                                suggested_action="Quarantine corrupted checkpoint file for offline inspection.",
                            )
                        )

        # 3. Check for broken ancestry references (parent_checkpoint_id or branch_source)
        for chk_file, act_id, chk_id in checkpoints_to_validate:
            try:
                with open(chk_file, "r", encoding="utf-8") as f:
                    chk_data = json.load(f)
                parent_id = chk_data.get("parent_checkpoint_id")
                branch_src = chk_data.get("branch_source_checkpoint_id")

                if parent_id and parent_id not in known_checkpoint_ids:
                    issues.append(
                        ConsistencyIssue(
                            issue_type=ConsistencyIssueType.INVALID_BRANCH_REFERENCE,
                            file_path=str(chk_file),
                            entity_id=chk_id,
                            activity_id=act_id,
                            description=f"Checkpoint '{chk_id}' references non-existent parent '{parent_id}'.",
                            remediable=True,
                            suggested_action="Isolate broken parent link in metadata without deleting checkpoint.",
                        )
                    )

                if branch_src and branch_src not in known_checkpoint_ids:
                    issues.append(
                        ConsistencyIssue(
                            issue_type=ConsistencyIssueType.INVALID_BRANCH_REFERENCE,
                            file_path=str(chk_file),
                            entity_id=chk_id,
                            activity_id=act_id,
                            description=f"Checkpoint '{chk_id}' references non-existent branch source '{branch_src}'.",
                            remediable=True,
                            suggested_action="Isolate broken branch link in metadata without deleting checkpoint.",
                        )
                    )
            except Exception:
                pass

        # 4. Check derived SQLite index synchronization
        if self.db_path.exists():
            try:
                with self.store._get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM activities_idx")
                    indexed_acts = cur.fetchone()[0]
                    cur.execute("SELECT COUNT(*) FROM checkpoints_idx")
                    indexed_chks = cur.fetchone()[0]

                if indexed_acts != total_activities or indexed_chks != total_checkpoints:
                    issues.append(
                        ConsistencyIssue(
                            issue_type=ConsistencyIssueType.DERIVED_INDEX_MISMATCH,
                            file_path=str(self.db_path),
                            entity_id=None,
                            activity_id=None,
                            description=(
                                f"Index mismatch: authoritative files ({total_activities} activities, {total_checkpoints} checkpoints) "
                                f"differ from SQLite index ({indexed_acts} activities, {indexed_chks} checkpoints)."
                            ),
                            remediable=True,
                            suggested_action="Rebuild SQLite index from authoritative JSON files.",
                        )
                    )
            except Exception as e:
                issues.append(
                    ConsistencyIssue(
                        issue_type=ConsistencyIssueType.DERIVED_INDEX_MISMATCH,
                        file_path=str(self.db_path),
                        entity_id=None,
                        activity_id=None,
                        description=f"SQLite index corrupted or inaccessible: {e}",
                        remediable=True,
                        suggested_action="Rebuild SQLite index from authoritative JSON files.",
                    )
                )

        return ConsistencyAuditReport(
            workspace_root=str(self.workspace_root),
            audited_at=datetime.now(timezone.utc).isoformat(),
            total_activities_found=total_activities,
            total_checkpoints_found=total_checkpoints,
            issues_found=issues,
        )

    def repair(self, dry_run: bool = False) -> ConsistencyRepairResult:
        """
        Executes safe, non-destructive repair for all detected anomalies.
        Guarantees:
        - Malformed files are quarantined, never deleted.
        - Missing activity records are reconstructed with their checkpoints preserved.
        - Broken ancestry links are documented in metadata.
        - Derived SQLite index is rebuilt cleanly.
        - Idempotent and repeatable.
        """
        audit_report = self.audit()
        if audit_report.is_clean:
            return ConsistencyRepairResult(
                workspace_root=str(self.workspace_root),
                repaired_at=datetime.now(timezone.utc).isoformat(),
                is_dry_run=dry_run,
                issues_detected=0,
                issues_repaired=0,
                is_clean_post_repair=True,
                details="Storage is clean. No repair required.",
            )

        if dry_run:
            return ConsistencyRepairResult(
                workspace_root=str(self.workspace_root),
                repaired_at=datetime.now(timezone.utc).isoformat(),
                is_dry_run=True,
                issues_detected=len(audit_report.issues_found),
                issues_repaired=0,
                is_clean_post_repair=False,
                details=f"Dry run: {len(audit_report.issues_found)} issues would be repaired non-destructively.",
            )

        repaired_count = 0
        quarantined_files: List[str] = []
        needs_index_rebuild = False

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        active_quarantine = self.quarantine_dir / f"session_{ts}"

        for issue in audit_report.issues_found:
            # A. Stale temporary files
            if issue.issue_type == ConsistencyIssueType.STALE_TEMPORARY_FILE:
                p = Path(issue.file_path)
                if p.exists():
                    try:
                        p.unlink()
                        issue.repaired = True
                        issue.repair_details = "Removed stale temporary file."
                        repaired_count += 1
                    except OSError:
                        pass

            # B. Missing activity.json
            elif issue.issue_type == ConsistencyIssueType.MISSING_ACTIVITY_RECORD:
                act_id = issue.activity_id or "act_recovered"
                act_dir = self.activities_dir / act_id
                act_dir.mkdir(parents=True, exist_ok=True)
                act_file = act_dir / "activity.json"

                recovered_act = Activity.create_blank(
                    title=f"Recovered Activity ({act_id})",
                    description="Automatically reconstructed header preserving underlying checkpoints.",
                    activity_type=ActivityType.CODING,
                    custom_id=act_id,
                    tags=["recovered"],
                )
                with open(act_file, "w", encoding="utf-8") as f:
                    f.write(json.dumps(recovered_act.to_dict(), indent=2, ensure_ascii=False))

                issue.repaired = True
                issue.repair_details = f"Reconstructed activity header at {act_file.name}."
                repaired_count += 1
                needs_index_rebuild = True

            # C. Malformed records -> Quarantine
            elif issue.issue_type == ConsistencyIssueType.MALFORMED_RECORD:
                p = Path(issue.file_path)
                if p.exists():
                    active_quarantine.mkdir(parents=True, exist_ok=True)
                    target_quarantine = active_quarantine / p.name
                    shutil.move(str(p), str(target_quarantine))

                    # Write quarantine manifest explanation
                    manifest_file = active_quarantine / f"{p.name}.manifest.json"
                    manifest_data = {
                        "original_path": str(p),
                        "quarantined_at": datetime.now(timezone.utc).isoformat(),
                        "reason": issue.description,
                    }
                    manifest_file.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

                    quarantined_files.append(str(target_quarantine))
                    issue.repaired = True
                    issue.repair_details = f"Moved corrupted record to quarantine at {target_quarantine.name}."
                    repaired_count += 1
                    needs_index_rebuild = True

            # D. Invalid branch or parent reference
            elif issue.issue_type == ConsistencyIssueType.INVALID_BRANCH_REFERENCE:
                p = Path(issue.file_path)
                if p.exists():
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            chk_data = json.load(f)

                        # Isolate broken parent or branch link into metadata
                        if chk_data.get("parent_checkpoint_id"):
                            chk_data.setdefault("metadata", {})["unresolved_parent_id"] = chk_data["parent_checkpoint_id"]
                            chk_data["parent_checkpoint_id"] = None

                        if chk_data.get("branch_source_checkpoint_id"):
                            chk_data.setdefault("metadata", {})["unresolved_branch_source_id"] = chk_data["branch_source_checkpoint_id"]
                            chk_data["branch_source_checkpoint_id"] = None

                        with open(p, "w", encoding="utf-8") as f:
                            json.dump(chk_data, f, indent=2, ensure_ascii=False)

                        issue.repaired = True
                        issue.repair_details = "Isolated broken ancestry link in metadata and nulled reference."
                        repaired_count += 1
                        needs_index_rebuild = True
                    except Exception:
                        pass

            # E. Derived index mismatch
            elif issue.issue_type == ConsistencyIssueType.DERIVED_INDEX_MISMATCH:
                needs_index_rebuild = True
                issue.repaired = True
                issue.repair_details = "Scheduled SQLite index rebuild."
                repaired_count += 1

            # F. Orphaned checkpoints
            elif issue.issue_type == ConsistencyIssueType.ORPHANED_CHECKPOINT:
                p = Path(issue.file_path)
                if p.exists():
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            chk_data = json.load(f)
                        # Harmonize activity_id to match folder
                        folder_act_id = p.parent.parent.name
                        chk_data["activity_id"] = folder_act_id
                        with open(p, "w", encoding="utf-8") as f:
                            json.dump(chk_data, f, indent=2, ensure_ascii=False)

                        issue.repaired = True
                        issue.repair_details = f"Harmonized checkpoint activity_id to '{folder_act_id}'."
                        repaired_count += 1
                        needs_index_rebuild = True
                    except Exception:
                        pass

        # Rebuild derived index if any change occurred
        rebuilt_records = 0
        if needs_index_rebuild:
            rebuilt_records = self.store.rebuild_index_from_authoritative_files()

        # Re-verify post-repair integrity
        post_audit = self.audit()

        return ConsistencyRepairResult(
            workspace_root=str(self.workspace_root),
            repaired_at=datetime.now(timezone.utc).isoformat(),
            is_dry_run=False,
            issues_detected=len(audit_report.issues_found),
            issues_repaired=repaired_count,
            quarantined_files=quarantined_files,
            rebuilt_index_records=rebuilt_records,
            is_clean_post_repair=post_audit.is_clean,
            details=f"Repaired {repaired_count} of {len(audit_report.issues_found)} issues. Post-repair clean: {post_audit.is_clean}.",
        )
