"""
Project Continuum — Checkpoint Comparison & Diff Engine (v1.4.0)
================================================================
Milestone 39 - Phase 64: Checkpoint Comparison/Diffs.

Compares compatible checkpoints for:
- Changed / added / removed structured state
- Progress transitions (percentage and milestone deltas)
- Work completed (newly finished items, retracted items)
- Pending actions (newly scheduled, resolved/completed, persisting)
- Architectural decisions & rationale (new, modified, removed)
- Blockers & unresolved issues (new, resolved, persisting)
- Notes & context text diffs (unified diff format)
- Artifact references & snapshot metadata (size, hash, path without loading large files)

Invariants Enforced:
- I-03: Pure functional read-only comparison. History is never mutated.
- I-17: Output size bounds. Large text diffs and lists are clamped; artifact
  payloads are never loaded into memory during comparison.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import difflib
import json
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from core.checkpoint import (
    UniversalCheckpoint,
    DecisionRecord,
    ArtifactReference,
    ProvenanceRecord,
)


class IncompatibleCheckpointsError(ValueError):
    """Raised when two checkpoints cannot be compared due to incompatible lineage or invalid schemas."""
    pass


@dataclass
class ProgressDiff:
    """Represents differences in progress metrics between checkpoints."""
    from_progress: Dict[str, Any] = field(default_factory=dict)
    to_progress: Dict[str, Any] = field(default_factory=dict)
    percentage_before: Optional[float] = None
    percentage_after: Optional[float] = None
    percentage_delta: Optional[float] = None
    summary: str = "No progress change"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_progress": dict(self.from_progress),
            "to_progress": dict(self.to_progress),
            "percentage_before": self.percentage_before,
            "percentage_after": self.percentage_after,
            "percentage_delta": self.percentage_delta,
            "summary": self.summary,
        }


@dataclass
class ListDiff:
    """Represents added, removed, and persisting strings in a list field."""
    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    persisting: List[str] = field(default_factory=list)
    is_truncated: bool = False
    total_added: int = 0
    total_removed: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "added": list(self.added),
            "removed": list(self.removed),
            "persisting": list(self.persisting),
            "is_truncated": self.is_truncated,
            "total_added": self.total_added,
            "total_removed": self.total_removed,
        }


@dataclass
class DecisionDiffItem:
    """Represents changes to an individual architectural decision."""
    id: str
    decision: str
    change_type: str  # 'added', 'removed', 'modified'
    rationale_before: Optional[str] = None
    rationale_after: Optional[str] = None
    constraints_added: List[str] = field(default_factory=list)
    constraints_removed: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "decision": self.decision,
            "change_type": self.change_type,
            "rationale_before": self.rationale_before,
            "rationale_after": self.rationale_after,
            "constraints_added": list(self.constraints_added),
            "constraints_removed": list(self.constraints_removed),
        }


@dataclass
class DecisionsDiff:
    """Represents differences in architectural decisions between checkpoints."""
    added: List[DecisionDiffItem] = field(default_factory=list)
    removed: List[DecisionDiffItem] = field(default_factory=list)
    modified: List[DecisionDiffItem] = field(default_factory=list)
    unchanged_count: int = 0
    is_truncated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "added": [d.to_dict() for d in self.added],
            "removed": [d.to_dict() for d in self.removed],
            "modified": [d.to_dict() for d in self.modified],
            "unchanged_count": self.unchanged_count,
            "is_truncated": self.is_truncated,
        }


@dataclass
class ArtifactDiffItem:
    """Represents changes in artifact metadata without loading raw payload."""
    name: str
    path_or_uri: str
    change_type: str  # 'added', 'removed', 'modified', 'unchanged'
    size_before: Optional[int] = None
    size_after: Optional[int] = None
    size_delta_bytes: Optional[int] = None
    checksum_before: Optional[str] = None
    checksum_after: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path_or_uri": self.path_or_uri,
            "change_type": self.change_type,
            "size_before": self.size_before,
            "size_after": self.size_after,
            "size_delta_bytes": self.size_delta_bytes,
            "checksum_before": self.checksum_before,
            "checksum_after": self.checksum_after,
        }


@dataclass
class ArtifactsDiff:
    """Represents metadata-only artifact differences."""
    added: List[ArtifactDiffItem] = field(default_factory=list)
    removed: List[ArtifactDiffItem] = field(default_factory=list)
    modified: List[ArtifactDiffItem] = field(default_factory=list)
    unchanged_count: int = 0
    is_truncated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "added": [a.to_dict() for a in self.added],
            "removed": [a.to_dict() for a in self.removed],
            "modified": [a.to_dict() for a in self.modified],
            "unchanged_count": self.unchanged_count,
            "is_truncated": self.is_truncated,
        }


@dataclass
class StateDiff:
    """Represents differences in structured state dictionaries."""
    added_keys: List[str] = field(default_factory=list)
    removed_keys: List[str] = field(default_factory=list)
    changed_keys: List[str] = field(default_factory=list)
    changes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    is_truncated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "added_keys": list(self.added_keys),
            "removed_keys": list(self.removed_keys),
            "changed_keys": list(self.changed_keys),
            "changes": dict(self.changes),
            "is_truncated": self.is_truncated,
        }


@dataclass
class TextDiff:
    """Represents unified diff and metrics for text/notes differences."""
    has_changed: bool = False
    unified_diff: str = ""
    before_length: int = 0
    after_length: int = 0
    is_truncated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_changed": self.has_changed,
            "unified_diff": self.unified_diff,
            "before_length": self.before_length,
            "after_length": self.after_length,
            "is_truncated": self.is_truncated,
        }


@dataclass
class CheckpointDiffResult:
    """Complete, deterministic diff comparing two UniversalCheckpoints."""
    base_checkpoint_id: str
    target_checkpoint_id: str
    activity_id: str
    is_compatible: bool
    incompatibility_reason: Optional[str] = None
    has_changes: bool = False
    high_level_summary: str = "No changes"
    progress: ProgressDiff = field(default_factory=ProgressDiff)
    completed_work: ListDiff = field(default_factory=ListDiff)
    pending_actions: ListDiff = field(default_factory=ListDiff)
    decisions: DecisionsDiff = field(default_factory=DecisionsDiff)
    blockers: ListDiff = field(default_factory=ListDiff)
    context_notes: TextDiff = field(default_factory=TextDiff)
    structured_state: StateDiff = field(default_factory=StateDiff)
    artifacts: ArtifactsDiff = field(default_factory=ArtifactsDiff)
    time_delta_seconds: Optional[float] = None
    markdown_diff: str = ""
    compared_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_checkpoint_id": self.base_checkpoint_id,
            "target_checkpoint_id": self.target_checkpoint_id,
            "activity_id": self.activity_id,
            "is_compatible": self.is_compatible,
            "incompatibility_reason": self.incompatibility_reason,
            "has_changes": self.has_changes,
            "high_level_summary": self.high_level_summary,
            "progress": self.progress.to_dict(),
            "completed_work": self.completed_work.to_dict(),
            "pending_actions": self.pending_actions.to_dict(),
            "decisions": self.decisions.to_dict(),
            "blockers": self.blockers.to_dict(),
            "context_notes": self.context_notes.to_dict(),
            "structured_state": self.structured_state.to_dict(),
            "artifacts": self.artifacts.to_dict(),
            "time_delta_seconds": self.time_delta_seconds,
            "markdown_diff": self.markdown_diff,
            "compared_at": self.compared_at,
        }


class CheckpointDiffEngine:
    """
    Deterministic, bounded engine for comparing compatible UniversalCheckpoints.
    Zero side-effects; never mutates history or loads heavy artifacts into memory.
    """

    def __init__(
        self,
        max_list_items: int = 100,
        max_text_diff_chars: int = 4000,
        allow_cross_activity: bool = False,
    ):
        self.max_list_items = max(1, max_list_items)
        self.max_text_diff_chars = max(100, max_text_diff_chars)
        self.allow_cross_activity = allow_cross_activity

    def compare(
        self,
        base: Union[UniversalCheckpoint, Dict[str, Any]],
        target: Union[UniversalCheckpoint, Dict[str, Any]],
        compared_at: Optional[str] = None,
    ) -> CheckpointDiffResult:
        """
        Compares base checkpoint against target checkpoint.
        Returns a deterministic, human-understandable CheckpointDiffResult.
        """
        if compared_at is None:
            compared_at = datetime.now(timezone.utc).isoformat()
        # Convert dicts if necessary
        base_obj = UniversalCheckpoint.from_dict(base) if isinstance(base, dict) else base
        target_obj = UniversalCheckpoint.from_dict(target) if isinstance(target, dict) else target

        # Compatibility check
        if base_obj is None or target_obj is None:
            return CheckpointDiffResult(
                base_checkpoint_id=getattr(base_obj, "id", "unknown"),
                target_checkpoint_id=getattr(target_obj, "id", "unknown"),
                activity_id=getattr(base_obj, "activity_id", "unknown"),
                is_compatible=False,
                incompatibility_reason="One or both checkpoints are null or missing.",
                high_level_summary="Incompatible: Missing checkpoint reference",
                markdown_diff="> [!WARNING]\n> Cannot compare checkpoints: one or both checkpoints are missing.",
            )

        if not self.allow_cross_activity and (base_obj.activity_id != target_obj.activity_id):
            return CheckpointDiffResult(
                base_checkpoint_id=base_obj.id,
                target_checkpoint_id=target_obj.id,
                activity_id=base_obj.activity_id,
                is_compatible=False,
                incompatibility_reason=(
                    f"Checkpoints belong to different activities: '{base_obj.activity_id}' "
                    f"vs '{target_obj.activity_id}'."
                ),
                high_level_summary="Incompatible: Checkpoints belong to different activities",
                markdown_diff=(
                    f"> [!WARNING]\n> Cannot compare checkpoints: Base activity '{base_obj.activity_id}' "
                    f"does not match Target activity '{target_obj.activity_id}'."
                ),
            )

        # 1. Compare Progress
        progress_diff = self._compare_progress(base_obj.progress, target_obj.progress)

        # 2. Compare Completed Work
        work_diff = self._compare_string_lists(
            base_obj.completed_work or [],
            target_obj.completed_work or [],
        )

        # 3. Compare Pending Actions
        actions_diff = self._compare_string_lists(
            base_obj.pending_actions or [],
            target_obj.pending_actions or [],
        )

        # 4. Compare Decisions
        decisions_diff = self._compare_decisions(
            base_obj.decisions or [],
            target_obj.decisions or [],
        )

        # 5. Compare Blockers
        blockers_diff = self._compare_string_lists(
            base_obj.blockers or [],
            target_obj.blockers or [],
        )

        # 6. Compare Context / Notes (Unified Diff with text bounding)
        context_diff = self._compare_text(
            base_obj.context or "",
            target_obj.context or "",
            from_name=f"checkpoint_{base_obj.id}",
            to_name=f"checkpoint_{target_obj.id}",
        )

        # 7. Compare Structured State (Bounded key/value comparison)
        state_diff = self._compare_structured_state(
            base_obj.structured_state or {},
            target_obj.structured_state or {},
        )

        # 8. Compare Artifacts Metadata (Zero large file loading)
        artifacts_diff = self._compare_artifacts(
            base_obj.artifacts or [],
            target_obj.artifacts or [],
        )

        # 9. Time delta calculation
        time_delta = self._calculate_time_delta(base_obj.timestamp, target_obj.timestamp)

        # 10. Check if any changes exist
        has_changes = (
            bool(work_diff.added or work_diff.removed) or
            bool(actions_diff.added or actions_diff.removed) or
            bool(decisions_diff.added or decisions_diff.removed or decisions_diff.modified) or
            bool(blockers_diff.added or blockers_diff.removed) or
            context_diff.has_changed or
            bool(state_diff.added_keys or state_diff.removed_keys or state_diff.changed_keys) or
            bool(artifacts_diff.added or artifacts_diff.removed or artifacts_diff.modified) or
            (progress_diff.percentage_delta is not None and progress_diff.percentage_delta != 0.0)
        )

        # 11. Generate Deterministic High-Level Summary
        summary = self._generate_high_level_summary(
            work_diff, actions_diff, decisions_diff, blockers_diff, progress_diff, has_changes
        )

        # 12. Generate Formatted Markdown Diff
        md_diff = self._generate_markdown_diff(
            base_obj, target_obj, summary, progress_diff, work_diff, actions_diff,
            decisions_diff, blockers_diff, context_diff, artifacts_diff, state_diff
        )

        return CheckpointDiffResult(
            base_checkpoint_id=base_obj.id,
            target_checkpoint_id=target_obj.id,
            activity_id=base_obj.activity_id,
            is_compatible=True,
            incompatibility_reason=None,
            has_changes=has_changes,
            high_level_summary=summary,
            progress=progress_diff,
            completed_work=work_diff,
            pending_actions=actions_diff,
            decisions=decisions_diff,
            blockers=blockers_diff,
            context_notes=context_diff,
            structured_state=state_diff,
            artifacts=artifacts_diff,
            time_delta_seconds=time_delta,
            markdown_diff=md_diff,
            compared_at=compared_at,
        )

    # =========================================================================
    # INTERNAL COMPARISON HELPERS
    # =========================================================================

    def _extract_progress_percentage(self, prog: Any) -> Optional[float]:
        if isinstance(prog, (int, float)):
            return float(prog)
        if isinstance(prog, dict):
            for k in ("percentage", "percent", "progress", "progress_pct", "value"):
                val = prog.get(k)
                if isinstance(val, (int, float)):
                    return float(val)
        return None

    def _compare_progress(self, base_prog: Any, target_prog: Any) -> ProgressDiff:
        b_pct = self._extract_progress_percentage(base_prog)
        t_pct = self._extract_progress_percentage(target_prog)

        delta = None
        summary = "No progress change"

        if b_pct is not None and t_pct is not None:
            delta = round(t_pct - b_pct, 2)
            if delta > 0:
                summary = f"Progress advanced from {b_pct:.1f}% to {t_pct:.1f}% (+{delta:.1f}%)"
            elif delta < 0:
                summary = f"Progress reverted from {b_pct:.1f}% to {t_pct:.1f}% ({delta:.1f}%)"
            else:
                summary = f"Progress unchanged at {t_pct:.1f}%"
        elif t_pct is not None:
            summary = f"Progress set to {t_pct:.1f}%"

        return ProgressDiff(
            from_progress=base_prog if isinstance(base_prog, dict) else {"val": base_prog},
            to_progress=target_prog if isinstance(target_prog, dict) else {"val": target_prog},
            percentage_before=b_pct,
            percentage_after=t_pct,
            percentage_delta=delta,
            summary=summary,
        )

    def _compare_string_lists(self, base_list: List[str], target_list: List[str]) -> ListDiff:
        # Preserve uniqueness while calculating set differences deterministically
        base_set = set(base_list)
        target_set = set(target_list)

        added = sorted([item for item in target_list if item not in base_set])
        removed = sorted([item for item in base_list if item not in target_set])
        persisting = sorted([item for item in target_list if item in base_set])

        total_added = len(added)
        total_removed = len(removed)
        is_truncated = False

        if len(added) > self.max_list_items:
            added = added[:self.max_list_items]
            is_truncated = True

        if len(removed) > self.max_list_items:
            removed = removed[:self.max_list_items]
            is_truncated = True

        if len(persisting) > self.max_list_items:
            persisting = persisting[:self.max_list_items]
            is_truncated = True

        return ListDiff(
            added=added,
            removed=removed,
            persisting=persisting,
            is_truncated=is_truncated,
            total_added=total_added,
            total_removed=total_removed,
        )

    def _compare_decisions(
        self,
        base_decisions: List[DecisionRecord],
        target_decisions: List[DecisionRecord],
    ) -> DecisionsDiff:
        base_by_id = {d.id: d for d in base_decisions}
        target_by_id = {d.id: d for d in target_decisions}

        added: List[DecisionDiffItem] = []
        removed: List[DecisionDiffItem] = []
        modified: List[DecisionDiffItem] = []
        unchanged_count = 0

        # Check additions & modifications
        for d_id, t_dec in sorted(target_by_id.items(), key=lambda x: x[0]):
            if d_id not in base_by_id:
                added.append(DecisionDiffItem(
                    id=t_dec.id,
                    decision=t_dec.decision,
                    change_type="added",
                    rationale_after=t_dec.rationale,
                    constraints_added=list(t_dec.constraints or []),
                ))
            else:
                b_dec = base_by_id[d_id]
                has_decision_changed = (b_dec.decision != t_dec.decision)
                has_rationale_changed = (b_dec.rationale != t_dec.rationale)
                b_constraints = set(b_dec.constraints or [])
                t_constraints = set(t_dec.constraints or [])
                c_added = sorted(list(t_constraints - b_constraints))
                c_removed = sorted(list(b_constraints - t_constraints))

                if has_decision_changed or has_rationale_changed or c_added or c_removed:
                    modified.append(DecisionDiffItem(
                        id=t_dec.id,
                        decision=t_dec.decision,
                        change_type="modified",
                        rationale_before=b_dec.rationale if has_rationale_changed else None,
                        rationale_after=t_dec.rationale if has_rationale_changed else None,
                        constraints_added=c_added,
                        constraints_removed=c_removed,
                    ))
                else:
                    unchanged_count += 1

        # Check removals
        for d_id, b_dec in sorted(base_by_id.items(), key=lambda x: x[0]):
            if d_id not in target_by_id:
                removed.append(DecisionDiffItem(
                    id=b_dec.id,
                    decision=b_dec.decision,
                    change_type="removed",
                    rationale_before=b_dec.rationale,
                    constraints_removed=list(b_dec.constraints or []),
                ))

        is_truncated = False
        if len(added) > self.max_list_items:
            added = added[:self.max_list_items]
            is_truncated = True
        if len(removed) > self.max_list_items:
            removed = removed[:self.max_list_items]
            is_truncated = True
        if len(modified) > self.max_list_items:
            modified = modified[:self.max_list_items]
            is_truncated = True

        return DecisionsDiff(
            added=added,
            removed=removed,
            modified=modified,
            unchanged_count=unchanged_count,
            is_truncated=is_truncated,
        )

    def _compare_artifacts(
        self,
        base_artifacts: List[ArtifactReference],
        target_artifacts: List[ArtifactReference],
    ) -> ArtifactsDiff:
        # Match by path_or_uri (or name if path not given)
        def art_key(a: ArtifactReference) -> str:
            return a.path_or_uri or a.name

        base_by_key = {art_key(a): a for a in base_artifacts}
        target_by_key = {art_key(a): a for a in target_artifacts}

        added: List[ArtifactDiffItem] = []
        removed: List[ArtifactDiffItem] = []
        modified: List[ArtifactDiffItem] = []
        unchanged_count = 0

        for key, t_art in sorted(target_by_key.items(), key=lambda x: x[0]):
            if key not in base_by_key:
                added.append(ArtifactDiffItem(
                    name=t_art.name,
                    path_or_uri=t_art.path_or_uri,
                    change_type="added",
                    size_after=t_art.size_bytes,
                    checksum_after=t_art.checksum_sha256,
                ))
            else:
                b_art = base_by_key[key]
                size_changed = (b_art.size_bytes != t_art.size_bytes)
                hash_changed = (
                    b_art.checksum_sha256 and t_art.checksum_sha256 and
                    b_art.checksum_sha256 != t_art.checksum_sha256
                )

                if size_changed or hash_changed:
                    delta_bytes = None
                    if b_art.size_bytes is not None and t_art.size_bytes is not None:
                        delta_bytes = t_art.size_bytes - b_art.size_bytes

                    modified.append(ArtifactDiffItem(
                        name=t_art.name,
                        path_or_uri=t_art.path_or_uri,
                        change_type="modified",
                        size_before=b_art.size_bytes,
                        size_after=t_art.size_bytes,
                        size_delta_bytes=delta_bytes,
                        checksum_before=b_art.checksum_sha256,
                        checksum_after=t_art.checksum_sha256,
                    ))
                else:
                    unchanged_count += 1

        for key, b_art in sorted(base_by_key.items(), key=lambda x: x[0]):
            if key not in target_by_key:
                removed.append(ArtifactDiffItem(
                    name=b_art.name,
                    path_or_uri=b_art.path_or_uri,
                    change_type="removed",
                    size_before=b_art.size_bytes,
                    checksum_before=b_art.checksum_sha256,
                ))

        is_truncated = False
        if len(added) > self.max_list_items:
            added = added[:self.max_list_items]
            is_truncated = True
        if len(removed) > self.max_list_items:
            removed = removed[:self.max_list_items]
            is_truncated = True
        if len(modified) > self.max_list_items:
            modified = modified[:self.max_list_items]
            is_truncated = True

        return ArtifactsDiff(
            added=added,
            removed=removed,
            modified=modified,
            unchanged_count=unchanged_count,
            is_truncated=is_truncated,
        )

    def _compare_text(
        self,
        before_text: str,
        after_text: str,
        from_name: str = "before",
        to_name: str = "after",
    ) -> TextDiff:
        if before_text == after_text:
            return TextDiff(
                has_changed=False,
                unified_diff="",
                before_length=len(before_text),
                after_length=len(after_text),
                is_truncated=False,
            )

        b_lines = before_text.splitlines(keepends=True)
        a_lines = after_text.splitlines(keepends=True)

        diff_gen = difflib.unified_diff(
            b_lines,
            a_lines,
            fromfile=from_name,
            tofile=to_name,
            lineterm="",
        )
        diff_str = "\n".join(diff_gen)

        is_truncated = False
        if len(diff_str) > self.max_text_diff_chars:
            diff_str = (
                diff_str[:self.max_text_diff_chars] +
                "\n[... text diff truncated due to size bounds (I-17) ...]"
            )
            is_truncated = True

        return TextDiff(
            has_changed=True,
            unified_diff=diff_str,
            before_length=len(before_text),
            after_length=len(after_text),
            is_truncated=is_truncated,
        )

    def _compare_structured_state(
        self,
        base_state: Dict[str, Any],
        target_state: Dict[str, Any],
    ) -> StateDiff:
        b_keys = set(base_state.keys())
        t_keys = set(target_state.keys())

        added_keys = sorted(list(t_keys - b_keys))
        removed_keys = sorted(list(b_keys - t_keys))
        common_keys = sorted(list(b_keys & t_keys))

        changed_keys: List[str] = []
        changes: Dict[str, Dict[str, Any]] = {}

        for k in common_keys:
            b_val = base_state[k]
            t_val = target_state[k]
            if b_val != t_val:
                changed_keys.append(k)
                # Bound value size if serializing
                changes[k] = {
                    "before": self._bound_value(b_val),
                    "after": self._bound_value(t_val),
                }

        is_truncated = False
        if len(added_keys) > self.max_list_items:
            added_keys = added_keys[:self.max_list_items]
            is_truncated = True
        if len(removed_keys) > self.max_list_items:
            removed_keys = removed_keys[:self.max_list_items]
            is_truncated = True
        if len(changed_keys) > self.max_list_items:
            changed_keys = changed_keys[:self.max_list_items]
            is_truncated = True

        return StateDiff(
            added_keys=added_keys,
            removed_keys=removed_keys,
            changed_keys=changed_keys,
            changes=changes,
            is_truncated=is_truncated,
        )

    def _bound_value(self, val: Any) -> Any:
        val_str = str(val)
        if len(val_str) > 200:
            return val_str[:200] + "..."
        return val

    def _calculate_time_delta(self, ts_before: str, ts_after: str) -> Optional[float]:
        try:
            dt_before = datetime.fromisoformat(ts_before)
            dt_after = datetime.fromisoformat(ts_after)
            return round((dt_after - dt_before).total_seconds(), 2)
        except Exception:
            return None

    def _generate_high_level_summary(
        self,
        work_diff: ListDiff,
        actions_diff: ListDiff,
        decisions_diff: DecisionsDiff,
        blockers_diff: ListDiff,
        progress_diff: ProgressDiff,
        has_changes: bool,
    ) -> str:
        if not has_changes:
            return "No changes between checkpoints."

        parts: List[str] = []
        if work_diff.added:
            parts.append(f"+{len(work_diff.added)} work item{'s' if len(work_diff.added) > 1 else ''}")
        if work_diff.removed:
            parts.append(f"-{len(work_diff.removed)} work retracted")

        if actions_diff.added:
            parts.append(f"+{len(actions_diff.added)} action{'s' if len(actions_diff.added) > 1 else ''}")
        if actions_diff.removed:
            parts.append(f"{len(actions_diff.removed)} action{'s' if len(actions_diff.removed) > 1 else ''} completed/cleared")

        if decisions_diff.added:
            parts.append(f"+{len(decisions_diff.added)} decision{'s' if len(decisions_diff.added) > 1 else ''}")
        if decisions_diff.modified:
            parts.append(f"{len(decisions_diff.modified)} decision{'s' if len(decisions_diff.modified) > 1 else ''} updated")

        if blockers_diff.removed:
            parts.append(f"{len(blockers_diff.removed)} blocker{'s' if len(blockers_diff.removed) > 1 else ''} resolved")
        if blockers_diff.added:
            parts.append(f"+{len(blockers_diff.added)} blocker{'s' if len(blockers_diff.added) > 1 else ''}")

        if progress_diff.percentage_delta is not None and progress_diff.percentage_delta != 0.0:
            sign = "+" if progress_diff.percentage_delta > 0 else ""
            parts.append(f"progress {sign}{progress_diff.percentage_delta:.1f}%")

        if not parts:
            return "State/Context attributes updated."

        return ", ".join(parts)

    def _generate_markdown_diff(
        self,
        base: UniversalCheckpoint,
        target: UniversalCheckpoint,
        summary: str,
        progress: ProgressDiff,
        work: ListDiff,
        actions: ListDiff,
        decisions: DecisionsDiff,
        blockers: ListDiff,
        context: TextDiff,
        artifacts: ArtifactsDiff,
        state: StateDiff,
    ) -> str:
        lines: List[str] = []
        lines.append(f"### 🔍 Checkpoint Comparison: `{base.id}` ➔ `{target.id}`")
        lines.append(f"**Activity**: `{base.activity_id}` | **Summary**: {summary}\n")

        # Progress
        if progress.percentage_before is not None or progress.percentage_after is not None:
            lines.append("#### 📈 Progress Evolution")
            lines.append(f"- {progress.summary}\n")

        # Completed Work
        if work.added or work.removed:
            lines.append("#### ✅ Completed Work Evolution")
            for item in work.added:
                lines.append(f"- `[+] Added`: {item}")
            for item in work.removed:
                lines.append(f"- `[-] Retracted`: {item}")
            lines.append("")

        # Pending Actions
        if actions.added or actions.removed:
            lines.append("#### ⏳ Pending Actions Evolution")
            for item in actions.added:
                lines.append(f"- `[+] New Action`: {item}")
            for item in actions.removed:
                lines.append(f"- `[✓] Completed / Cleared`: {item}")
            lines.append("")

        # Decisions
        if decisions.added or decisions.modified or decisions.removed:
            lines.append("#### ⚖️ Architectural Decisions")
            for d in decisions.added:
                lines.append(f"- `[+] Added`: **{d.decision}** (ID: `{d.id}`)")
                if d.rationale_after:
                    lines.append(f"  * Rationale: {d.rationale_after}")
            for d in decisions.modified:
                lines.append(f"- `[Δ] Modified`: **{d.decision}** (ID: `{d.id}`)")
                if d.rationale_before and d.rationale_after:
                    lines.append(f"  * Rationale updated: *\"{d.rationale_before}\"* ➔ *\"{d.rationale_after}\"*")
                if d.constraints_added:
                    lines.append(f"  * Added Constraints: {', '.join(d.constraints_added)}")
                if d.constraints_removed:
                    lines.append(f"  * Removed Constraints: {', '.join(d.constraints_removed)}")
            for d in decisions.removed:
                lines.append(f"- `[-] Removed`: **{d.decision}** (ID: `{d.id}`)")
            lines.append("")

        # Blockers
        if blockers.added or blockers.removed:
            lines.append("#### 🚫 Blockers & Unresolved Issues")
            for b in blockers.removed:
                lines.append(f"- `[✓] Resolved`: {b}")
            for b in blockers.added:
                lines.append(f"- `[!] New Blocker`: {b}")
            lines.append("")

        # Artifacts
        if artifacts.added or artifacts.modified or artifacts.removed:
            lines.append("#### 📁 Artifacts Evolution")
            for a in artifacts.added:
                size_str = f" ({a.size_after} bytes)" if a.size_after is not None else ""
                lines.append(f"- `[+] Added`: `{a.path_or_uri or a.name}`{size_str}")
            for a in artifacts.modified:
                delta_str = f" (delta: {a.size_delta_bytes:+d} bytes)" if a.size_delta_bytes is not None else ""
                lines.append(f"- `[Δ] Modified`: `{a.path_or_uri or a.name}`{delta_str}")
            for a in artifacts.removed:
                lines.append(f"- `[-] Removed`: `{a.path_or_uri or a.name}`")
            lines.append("")

        # Context text diff
        if context.has_changed:
            lines.append("#### 📝 Context & Notes Diff")
            lines.append("```diff")
            lines.append(context.unified_diff)
            lines.append("```\n")

        # Structured state
        if state.added_keys or state.removed_keys or state.changed_keys:
            lines.append("#### ⚙️ Structured State Changes")
            if state.added_keys:
                lines.append(f"- **Added Keys**: {', '.join(state.added_keys)}")
            if state.removed_keys:
                lines.append(f"- **Removed Keys**: {', '.join(state.removed_keys)}")
            if state.changed_keys:
                lines.append(f"- **Changed Keys**: {', '.join(state.changed_keys)}")
            lines.append("")

        if not lines or len(lines) <= 2:
            lines.append("*No substantive changes detected between these two snapshots.*")

        return "\n".join(lines)
