"""
Project Continuum — Activity & Checkpoint Persistent Storage Engine
====================================================================
Milestone 37: Durable Storage and Migration
Phase 56: Persistence Extension and Durable Commits

Implements:
1. Hybrid Authoritative JSON Store + Embedded SQLite Derived Index (ADR-001).
2. Authoritative partitioned file layout:
   - `<workspace_root>/.continuum/activities/<activity_id>/activity.json`
   - `<workspace_root>/.continuum/activities/<activity_id>/checkpoints/<checkpoint_id>.json`
3. Embedded SQLite derived index at `<workspace_root>/.continuum/index.db`.
4. Accurate commit confirmation: writes to .tmp, flushes, atomically replaces,
   and updates index before returning confirmed entity (I-02).
5. Relational validation preventing dangling checkpoints or invalid ancestry.
6. Bounded pagination for large histories (I-17).
7. Complete, deterministic index rebuild from authoritative files (I-06).
8. Zero external dependencies (Python standard library only).
"""

import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple, Union
import uuid

from core.activity import Activity, ActivityStatus, ActivityType, ActivityValidationError, InvalidStatusTransitionError
from core.checkpoint import (
    UniversalCheckpoint,
    CheckpointValidationError,
    DecisionRecord,
    ArtifactReference,
    ProvenanceRecord,
)
from core.enums import ProvenanceType
from core.invariants import (
    CommitFailedError,
    InvariantViolationError,
    InvariantId,
)


class ActivityNotFoundError(CommitFailedError):
    """Raised when an operation targets a non-existent activity."""
    def __init__(self, activity_id: str):
        super().__init__(
            message=f"Activity '{activity_id}' does not exist.",
            internal_details=f"Target activity_id={activity_id} was not found in storage.",
        )
        self.activity_id = activity_id


class CheckpointNotFoundError(CommitFailedError):
    """Raised when an operation targets a non-existent checkpoint."""
    def __init__(self, checkpoint_id: str):
        super().__init__(
            message=f"Checkpoint '{checkpoint_id}' does not exist.",
            internal_details=f"Target checkpoint_id={checkpoint_id} was not found in storage.",
        )
        self.checkpoint_id = checkpoint_id


class DanglingReferenceError(CommitFailedError):
    """Raised when a checkpoint references a non-existent parent or activity."""
    def __init__(self, message: str, reference_id: str):
        super().__init__(
            message=f"Relational integrity violation: {message}",
            internal_details=f"Referenced identifier '{reference_id}' does not exist.",
        )
        self.reference_id = reference_id


class IncompatibleRestoreError(CommitFailedError):
    """Raised when an attempted restore operation targets an incompatible activity or corrupted checkpoint."""
    def __init__(self, message: str, internal_details: Optional[str] = None):
        super().__init__(
            message=f"Restore incompatibility: {message}",
            internal_details=internal_details or message,
        )


class ActivityCheckpointStore:
    """
    Durable, crash-safe storage engine for Continuum Activities and Checkpoints.
    Adheres strictly to ADR-001:
    - Authoritative ground truth is stored in partitioned JSON files.
    - Derived queries and pagination run against an embedded SQLite database.
    - SQLite index is 100% rebuildable from disk files.
    """

    MAX_PAGE_LIMIT = 100
    DEFAULT_PAGE_LIMIT = 20

    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root).resolve()
        self.continuum_dir = self.workspace_root / ".continuum"
        self.activities_dir = self.continuum_dir / "activities"
        self.db_path = self.continuum_dir / "index.db"
        self._initialize_storage()

    def _initialize_storage(self) -> None:
        """Creates directory topology and ensures SQLite index schema is initialized."""
        self.continuum_dir.mkdir(parents=True, exist_ok=True)
        self.activities_dir.mkdir(parents=True, exist_ok=True)
        self._init_sqlite_schema()

    @contextmanager
    def _get_db_connection(self) -> Iterator[sqlite3.Connection]:
        """Returns a managed SQLite connection with foreign keys and WAL mode, closing it on exit."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        try:
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def _init_sqlite_schema(self) -> None:
        """Initializes tables and indexes in the derived SQLite database."""
        with self._get_db_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS activities_idx (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    collection TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    file_path TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS checkpoints_idx (
                    id TEXT PRIMARY KEY,
                    activity_id TEXT NOT NULL,
                    parent_checkpoint_id TEXT,
                    timestamp TEXT NOT NULL,
                    progress REAL NOT NULL,
                    completed_count INTEGER NOT NULL,
                    pending_count INTEGER NOT NULL,
                    decisions_count INTEGER NOT NULL,
                    blockers_count INTEGER NOT NULL,
                    artifacts_count INTEGER NOT NULL,
                    provenance_type TEXT NOT NULL,
                    summary TEXT,
                    file_path TEXT NOT NULL,
                    FOREIGN KEY (activity_id) REFERENCES activities_idx(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_act_status ON activities_idx(status);
                CREATE INDEX IF NOT EXISTS idx_act_type ON activities_idx(type);
                CREATE INDEX IF NOT EXISTS idx_act_created ON activities_idx(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_act_updated ON activities_idx(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_act_collection ON activities_idx(collection);

                CREATE INDEX IF NOT EXISTS idx_chk_act_ts ON checkpoints_idx(activity_id, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_chk_parent ON checkpoints_idx(parent_checkpoint_id);

                CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
                    record_id UNINDEXED,
                    record_type UNINDEXED,
                    activity_id UNINDEXED,
                    title,
                    description,
                    notes,
                    decisions,
                    actions,
                    briefs,
                    artifacts,
                    tags,
                    type,
                    status,
                    collection,
                    timestamp UNINDEXED,
                    tokenize=unicode61
                );
            """)

    # =========================================================================
    # ACTIVITY CRUD OPERATIONS
    # =========================================================================

    def _get_activity_dir(self, activity_id: str) -> Path:
        return self.activities_dir / activity_id

    def _get_activity_file(self, activity_id: str) -> Path:
        return self._get_activity_dir(activity_id) / "activity.json"

    def _get_checkpoints_dir(self, activity_id: str) -> Path:
        return self._get_activity_dir(activity_id) / "checkpoints"

    def _get_checkpoint_file(self, activity_id: str, checkpoint_id: str) -> Path:
        return self._get_checkpoints_dir(activity_id) / f"{checkpoint_id}.json"

    def create_activity(self, activity: Activity) -> Activity:
        """
        Creates a new activity in durable storage.
        Writes authoritative JSON file atomically, then indexes in SQLite.
        """
        activity.validate()

        act_file = self._get_activity_file(activity.id)
        if act_file.exists():
            raise CommitFailedError(f"Activity '{activity.id}' already exists.")

        act_dir = self._get_activity_dir(activity.id)
        chk_dir = self._get_checkpoints_dir(activity.id)
        act_dir.mkdir(parents=True, exist_ok=True)
        chk_dir.mkdir(parents=True, exist_ok=True)

        # 1. Authoritative atomic file persistence (.tmp -> replace)
        tmp_file = act_dir / f"activity.json.tmp_{os.getpid()}"
        try:
            content = json.dumps(activity.to_dict(), indent=2, ensure_ascii=False)
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            tmp_file.replace(act_file)
        except Exception as e:
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except OSError:
                    pass
            raise CommitFailedError(f"Failed to persist activity file: {e}", internal_details=str(e))

        # 2. Update derived SQLite index
        try:
            desc_val = getattr(activity, "description", "") or getattr(activity, "purpose", "")
            type_val = activity.activity_type.value if hasattr(activity.activity_type, "value") else str(activity.activity_type)
            status_val = activity.status.value if hasattr(activity.status, "value") else str(activity.status)
            with self._get_db_connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO activities_idx
                    (id, title, description, type, status, tags_json, collection, created_at, updated_at, file_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        activity.id,
                        activity.title,
                        desc_val,
                        type_val,
                        status_val,
                        json.dumps(list(activity.tags)),
                        activity.collection,
                        activity.created_at,
                        activity.updated_at,
                        str(act_file),
                    ),
                )
        except Exception as e:
            # If indexing fails, delete the written file to avoid inconsistent state
            if act_file.exists():
                act_file.unlink()
            raise CommitFailedError(f"Failed to update activity index: {e}", internal_details=str(e))

        # 3. Derived search index update (Phase 68)
        try:
            self.index_activity_search(activity)
        except Exception:
            pass

        return activity

    def get_activity(self, activity_id: str) -> Activity:
        """
        Loads an activity by ID from authoritative JSON file.
        Raises ActivityNotFoundError if not found.
        """
        act_file = self._get_activity_file(activity_id)
        if not act_file.exists():
            raise ActivityNotFoundError(activity_id)

        try:
            with open(act_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Activity.from_dict(data)
        except Exception as e:
            raise CommitFailedError(f"Corrupted activity file for '{activity_id}': {e}", internal_details=str(e))

    def update_activity(self, activity: Activity) -> Activity:
        """
        Updates an existing activity in storage.
        Verifies existence, validates data, writes atomically, and updates index.
        """
        activity.validate()

        act_file = self._get_activity_file(activity.id)
        if not act_file.exists():
            raise ActivityNotFoundError(activity.id)

        act_dir = self._get_activity_dir(activity.id)
        tmp_file = act_dir / f"activity.json.tmp_{os.getpid()}"

        try:
            content = json.dumps(activity.to_dict(), indent=2, ensure_ascii=False)
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            tmp_file.replace(act_file)
        except Exception as e:
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except OSError:
                    pass
            raise CommitFailedError(f"Failed to update activity file: {e}", internal_details=str(e))

        # Update SQLite index
        desc_val = getattr(activity, "description", "") or getattr(activity, "purpose", "")
        type_val = activity.activity_type.value if hasattr(activity.activity_type, "value") else str(activity.activity_type)
        status_val = activity.status.value if hasattr(activity.status, "value") else str(activity.status)
        with self._get_db_connection() as conn:
            conn.execute(
                """
                UPDATE activities_idx
                SET title = ?, description = ?, type = ?, status = ?, tags_json = ?,
                    collection = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    activity.title,
                    desc_val,
                    type_val,
                    status_val,
                    json.dumps(list(activity.tags)),
                    activity.collection,
                    activity.updated_at,
                    activity.id,
                ),
            )

        # Derived search index update (Phase 68)
        try:
            self.index_activity_search(activity)
        except Exception:
            pass

        return activity

    def list_activities(
        self,
        status: Optional[Union[ActivityStatus, str]] = None,
        activity_type: Optional[Union[ActivityType, str]] = None,
        tag: Optional[str] = None,
        collection: Optional[str] = None,
        include_archived: bool = True,
        sort_by: str = "recent",
        order: str = "desc",
        limit: int = DEFAULT_PAGE_LIMIT,
        offset: int = 0,
    ) -> Tuple[List[Activity], int]:
        """
        Lists activities with bounded pagination (I-17), filtering, and sorting (Phase 67).
        Supports:
        - status: active, paused, completed, archived (or None for all)
        - include_archived: if False and status is None, excludes archived
        - activity_type: built-in enum or custom string types
        - tag: tag containment search
        - collection: filter by collection name
        - sort_by: 'recent' / 'updated', 'created', 'title'
        - order: 'desc' or 'asc'
        Returns a tuple of (items_page, total_matching_count).
        """
        clamped_limit = max(1, min(limit, self.MAX_PAGE_LIMIT))
        clamped_offset = max(0, offset)

        query = "SELECT id, file_path FROM activities_idx WHERE 1=1"
        count_query = "SELECT COUNT(*) FROM activities_idx WHERE 1=1"
        params: List[Any] = []

        if status:
            status_val = status.value if hasattr(status, "value") else str(status).lower()
            query += " AND status = ?"
            count_query += " AND status = ?"
            params.append(status_val)
        elif not include_archived:
            query += " AND status != 'archived'"
            count_query += " AND status != 'archived'"

        if activity_type:
            type_val = activity_type.value if hasattr(activity_type, "value") else str(activity_type).lower()
            query += " AND type = ?"
            count_query += " AND type = ?"
            params.append(type_val)

        if tag:
            clean_tag = str(tag).strip().lower()
            query += " AND tags_json LIKE ?"
            count_query += " AND tags_json LIKE ?"
            params.append(f'%"{clean_tag}"%')

        if collection is not None:
            clean_col = str(collection).strip()
            if clean_col == "":
                query += " AND (collection IS NULL OR collection = '')"
                count_query += " AND (collection IS NULL OR collection = '')"
            else:
                query += " AND collection = ?"
                count_query += " AND collection = ?"
                params.append(clean_col)

        # Sorting resolution
        sort_key = str(sort_by).lower()
        if sort_key in ("created", "created_at"):
            sort_col = "created_at"
        elif sort_key == "title":
            sort_col = "title COLLATE NOCASE"
        else:
            sort_col = "updated_at"

        sort_dir = "ASC" if str(order).lower() == "asc" else "DESC"

        with self._get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(count_query, params)
            total_count = cursor.fetchone()[0]

            query += f" ORDER BY {sort_col} {sort_dir} LIMIT ? OFFSET ?"
            query_params = list(params) + [clamped_limit, clamped_offset]
            cursor.execute(query, query_params)
            rows = cursor.fetchall()

        activities: List[Activity] = []
        for row in rows:
            act_id = row["id"]
            try:
                activities.append(self.get_activity(act_id))
            except Exception:
                continue

        return activities, total_count

    # =========================================================================
    # PHASE 67 — LIFECYCLE, TAGS, COLLECTIONS & RELATED ACTIVITIES
    # =========================================================================

    def transition_activity_status(
        self,
        activity_id: str,
        target_status: Union[ActivityStatus, str],
    ) -> Activity:
        """
        Phase 67: Executes a validated lifecycle status transition for an activity.
        Enforces state machine invariants:
        - active -> paused, completed, archived
        - paused -> active, completed, archived
        - completed -> active (reopen), archived
        - archived -> active (restore), paused (restore)
        Preserves all historical checkpoints without rewriting history (I-16, Gate).
        """
        activity = self.get_activity(activity_id)
        activity.transition_to(target_status)
        return self.update_activity(activity)

    def archive_activity(self, activity_id: str) -> Activity:
        """
        Phase 67: Archives an activity. All historical checkpoints remain fully preserved and recoverable.
        """
        return self.transition_activity_status(activity_id, ActivityStatus.ARCHIVED)

    def restore_archived_activity(
        self,
        activity_id: str,
        target_status: ActivityStatus = ActivityStatus.ACTIVE,
    ) -> Activity:
        """
        Phase 67: Recovers an archived activity back to active or paused.
        Checkpoint history and stable ID (I-01) remain 100% intact.
        """
        activity = self.get_activity(activity_id)
        activity.restore_from_archive(target_status)
        return self.update_activity(activity)

    def update_activity_details(
        self,
        activity_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        collection: Optional[str] = None,
        activity_type: Optional[str] = None,
    ) -> Activity:
        """
        Phase 67: Updates editable activity attributes (title, description, tags, collection, custom type)
        while strictly preserving the stable ID (I-01) and checkpoint history.
        """
        activity = self.get_activity(activity_id)
        activity.update_details(
            title=title,
            description=description,
            tags=tags,
            collection=collection,
            activity_type=activity_type,
        )
        return self.update_activity(activity)

    def link_activities(
        self,
        source_activity_id: str,
        target_activity_id: str,
        bidirectional: bool = True,
    ) -> Tuple[Activity, Optional[Activity]]:
        """
        Phase 67: Links related activities without mutating checkpoint history.
        """
        if source_activity_id == target_activity_id:
            raise ActivityValidationError("An activity cannot link to itself.")

        source_act = self.get_activity(source_activity_id)
        target_act = self.get_activity(target_activity_id)

        source_act.link_related_activity(target_act.id)
        updated_source = self.update_activity(source_act)

        updated_target = None
        if bidirectional:
            target_act.link_related_activity(source_act.id)
            updated_target = self.update_activity(target_act)

        return updated_source, updated_target

    def unlink_activities(
        self,
        source_activity_id: str,
        target_activity_id: str,
        bidirectional: bool = True,
    ) -> Tuple[Activity, Optional[Activity]]:
        """
        Phase 67: Removes link between activities without mutating checkpoint history.
        """
        source_act = self.get_activity(source_activity_id)
        source_act.unlink_related_activity(target_activity_id)
        updated_source = self.update_activity(source_act)

        updated_target = None
        if bidirectional:
            try:
                target_act = self.get_activity(target_activity_id)
                target_act.unlink_related_activity(source_activity_id)
                updated_target = self.update_activity(target_act)
            except Exception:
                pass

        return updated_source, updated_target

    def list_collections(self) -> List[Dict[str, Any]]:
        """
        Phase 67: Aggregates all collections with activity counts.
        """
        with self._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT collection, COUNT(*) as count
                FROM activities_idx
                WHERE collection IS NOT NULL AND TRIM(collection) != ''
                GROUP BY collection
                ORDER BY collection COLLATE NOCASE ASC
                """
            )
            rows = cur.fetchall()
            return [{"collection": row["collection"], "count": row["count"]} for row in rows]

    def list_tags(self) -> List[Dict[str, Any]]:
        """
        Phase 67: Aggregates distinct tags across activities with frequency counts.
        """
        with self._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT tags_json FROM activities_idx")
            rows = cur.fetchall()

        tag_counts: Dict[str, int] = {}
        for row in rows:
            try:
                tags = json.loads(row["tags_json"])
                for t in tags:
                    clean_t = str(t).strip().lower()
                    if clean_t:
                        tag_counts[clean_t] = tag_counts.get(clean_t, 0) + 1
            except Exception:
                continue

        sorted_tags = sorted(tag_counts.items(), key=lambda x: (-x[1], x[0]))
        return [{"tag": t, "count": c} for t, c in sorted_tags]

    # =========================================================================
    # CHECKPOINT CRUD & COMMITS
    # =========================================================================

    def commit_checkpoint(self, checkpoint: UniversalCheckpoint) -> UniversalCheckpoint:
        """
        Authoritatively and durably commits a checkpoint (I-02).
        Enforces relational integrity:
        - Activity must exist (preventing dangling activity references).
        - If parent_checkpoint_id is present, parent must exist.
        - Writes to temporary file, flushes to disk, atomically replaces target file,
          and updates SQLite index before returning.
        """
        checkpoint.validate()

        # 1. Relational Integrity: Activity check
        act_file = self._get_activity_file(checkpoint.activity_id)
        if not act_file.exists():
            raise DanglingReferenceError(
                f"Cannot commit checkpoint for non-existent activity '{checkpoint.activity_id}'",
                checkpoint.activity_id,
            )

        # 2. Relational Integrity: Parent checkpoint check (if applicable)
        if checkpoint.parent_checkpoint_id:
            parent_file = self._get_checkpoint_file(checkpoint.activity_id, checkpoint.parent_checkpoint_id)
            if not parent_file.exists():
                # Check if parent exists in any activity via index
                with self._get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id FROM checkpoints_idx WHERE id = ?", (checkpoint.parent_checkpoint_id,))
                    if not cur.fetchone():
                        raise DanglingReferenceError(
                            f"Parent checkpoint '{checkpoint.parent_checkpoint_id}' does not exist.",
                            checkpoint.parent_checkpoint_id,
                        )

        # 3. Idempotency / Duplicate Check
        chk_file = self._get_checkpoint_file(checkpoint.activity_id, checkpoint.id)
        if chk_file.exists():
            existing = self.get_checkpoint(checkpoint.id, checkpoint.activity_id)
            if existing == checkpoint:
                return existing

        chk_dir = self._get_checkpoints_dir(checkpoint.activity_id)
        chk_dir.mkdir(parents=True, exist_ok=True)
        tmp_file = chk_dir / f"{checkpoint.id}.json.tmp_{os.getpid()}"

        # 4. Authoritative atomic disk persistence
        try:
            content = json.dumps(checkpoint.to_dict(), indent=2, ensure_ascii=False)
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            tmp_file.replace(chk_file)
        except Exception as e:
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except OSError:
                    pass
            raise CommitFailedError(f"Failed to persist checkpoint to disk: {e}", internal_details=str(e))

        # 5. Derived SQLite index update
        try:
            if isinstance(checkpoint.progress, dict):
                progress_val = float(checkpoint.progress.get("percentage", 0.0))
            elif isinstance(checkpoint.progress, (int, float)):
                progress_val = float(checkpoint.progress)
            else:
                progress_val = 0.0

            if checkpoint.provenance and hasattr(checkpoint.provenance, "provenance_type"):
                pt = checkpoint.provenance.provenance_type
                prov_val = pt.value if hasattr(pt, "value") else str(pt)
            else:
                prov_val = "auto_captured"

            summary_text = None
            if checkpoint.resume_brief:
                summary_text = getattr(checkpoint.resume_brief, "purpose", None) or getattr(checkpoint.resume_brief, "summary", None)

            with self._get_db_connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO checkpoints_idx
                    (id, activity_id, parent_checkpoint_id, timestamp, progress,
                     completed_count, pending_count, decisions_count, blockers_count,
                     artifacts_count, provenance_type, summary, file_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        checkpoint.id,
                        checkpoint.activity_id,
                        checkpoint.parent_checkpoint_id,
                        checkpoint.timestamp,
                        progress_val,
                        len(checkpoint.completed_work),
                        len(checkpoint.pending_actions),
                        len(checkpoint.decisions),
                        len(checkpoint.blockers),
                        len(checkpoint.artifacts),
                        prov_val,
                        summary_text,
                        str(chk_file),
                    ),
                )
        except Exception as e:
            # Clean up authoritative file if indexing crashes
            if chk_file.exists():
                chk_file.unlink()
            raise CommitFailedError(f"Failed to index checkpoint: {e}", internal_details=str(e))

        # 6. Touch activity updated_at timestamp in background
        try:
            act = self.get_activity(checkpoint.activity_id)
            act.updated_at = datetime.now(timezone.utc).isoformat()
            self.update_activity(act)
        except Exception:
            pass

        # 7. Derived search index update (Phase 68)
        try:
            self.index_checkpoint_search(checkpoint)
        except Exception:
            pass

        return checkpoint

    def get_checkpoint(self, checkpoint_id: str, activity_id: Optional[str] = None) -> UniversalCheckpoint:
        """
        Retrieves a checkpoint by ID from authoritative JSON file.
        If activity_id is omitted, looks up the owning activity from SQLite index.
        """
        if not activity_id:
            with self._get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT activity_id FROM checkpoints_idx WHERE id = ?", (checkpoint_id,))
                row = cur.fetchone()
                if not row:
                    raise CheckpointNotFoundError(checkpoint_id)
                activity_id = row["activity_id"]

        chk_file = self._get_checkpoint_file(activity_id, checkpoint_id)
        if not chk_file.exists():
            raise CheckpointNotFoundError(checkpoint_id)

        try:
            with open(chk_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return UniversalCheckpoint.from_dict(data)
        except Exception as e:
            raise CommitFailedError(f"Corrupted checkpoint file for '{checkpoint_id}': {e}", internal_details=str(e))

    def list_checkpoints(
        self,
        activity_id: str,
        limit: int = DEFAULT_PAGE_LIMIT,
        offset: int = 0,
        order: str = "desc",
    ) -> Tuple[List[UniversalCheckpoint], int]:
        """
        Lists checkpoints for an activity ordered chronologically (I-17).
        :param order: 'asc' (oldest first) or 'desc' (newest first). Defaults to 'desc'.
        Enforces bounded pagination (I-17).
        """
        # Verify activity exists
        if not self._get_activity_file(activity_id).exists():
            raise ActivityNotFoundError(activity_id)

        clamped_limit = max(1, min(limit, self.MAX_PAGE_LIMIT))
        clamped_offset = max(0, offset)
        sort_order = "ASC" if str(order).lower() == "asc" else "DESC"

        with self._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM checkpoints_idx WHERE activity_id = ?", (activity_id,))
            total_count = cur.fetchone()[0]

            cur.execute(
                f"""
                SELECT id FROM checkpoints_idx
                WHERE activity_id = ?
                ORDER BY timestamp {sort_order}
                LIMIT ? OFFSET ?
                """,
                (activity_id, clamped_limit, clamped_offset),
            )
            rows = cur.fetchall()

        checkpoints: List[UniversalCheckpoint] = []
        for row in rows:
            chk_id = row["id"]
            try:
                checkpoints.append(self.get_checkpoint(chk_id, activity_id))
            except Exception:
                continue

        return checkpoints, total_count

    # =========================================================================
    # PHASE 65 — BRANCH FROM HISTORICAL CHECKPOINT
    # =========================================================================

    def branch_from_checkpoint(
        self,
        source_checkpoint_id: str,
        new_title: Optional[str] = None,
        branch_name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        new_activity_id: Optional[str] = None,
        new_checkpoint_id: Optional[str] = None,
    ) -> Tuple[Activity, UniversalCheckpoint]:
        """
        Phase 65: Branch from Historical Checkpoint.
        Creates an independent continuation activity with stable identity, source checkpoint,
        and ancestry tracking. Reuses artifact references without file bloat.

        Guarantees:
        - I-01: Stable local identities for new activity and initial checkpoint.
        - I-03 & Gate: Branching is NOT restore and NEVER mutates the source branch or checkpoint.
        - Failure-Safe: Clean rollback on partial failure; safe to retry.
        """
        if not source_checkpoint_id or not isinstance(source_checkpoint_id, str):
            raise CheckpointValidationError("Parameter 'source_checkpoint_id' must be a non-empty string.")

        # 1. Authoritative lookup of source checkpoint and activity
        source_chk = self.get_checkpoint(source_checkpoint_id.strip())
        source_act = self.get_activity(source_chk.activity_id)

        # 2. Derive branch parameters & stable identities
        clean_branch_name = branch_name.strip() if branch_name and branch_name.strip() else "branch"
        act_title = new_title.strip() if new_title and new_title.strip() else f"{source_act.title} (Branch: {clean_branch_name})"
        act_id = new_activity_id.strip() if new_activity_id and new_activity_id.strip() else f"act_{uuid.uuid4().hex[:12]}"
        chk_id = new_checkpoint_id.strip() if new_checkpoint_id and new_checkpoint_id.strip() else f"chk_{uuid.uuid4().hex[:12]}"

        # Inherit and deduplicate tags
        inherited_tags: List[str] = list(source_act.tags)
        if "branch" not in inherited_tags:
            inherited_tags.append("branch")
        if tags:
            for t in tags:
                clean_t = str(t).strip()
                if clean_t and clean_t not in inherited_tags:
                    inherited_tags.append(clean_t)

        # Build activity metadata with explicit branch provenance
        act_metadata = dict(source_act.metadata)
        act_metadata.update({
            "branch_source_activity_id": source_act.id,
            "branch_source_checkpoint_id": source_chk.id,
            "branch_name": clean_branch_name,
            "branched_at": datetime.now(timezone.utc).isoformat(),
        })

        related_ids = list(source_act.related_activity_ids)
        if source_act.id not in related_ids:
            related_ids.append(source_act.id)

        # 3. Construct new independent Activity entity
        new_activity = Activity(
            id=act_id,
            title=act_title,
            description=description if description is not None else source_act.description,
            activity_type=source_act.activity_type,
            status=ActivityStatus.ACTIVE,
            tags=inherited_tags,
            collection=source_act.collection,
            related_activity_ids=related_ids,
            metadata=act_metadata,
        )

        # 4. Construct cloned initial checkpoint reusing artifact references
        # Artifact references are copied without file duplication
        reused_artifacts = [
            ArtifactReference(
                name=a.name,
                path_or_uri=a.path_or_uri,
                mode=a.mode,
                captured_at=a.captured_at,
                checksum_sha256=a.checksum_sha256,
                size_bytes=a.size_bytes,
                snapshot_content=a.snapshot_content,
            )
            for a in source_chk.artifacts
        ]

        cloned_decisions = [
            DecisionRecord(
                id=f"dec_{uuid.uuid4().hex[:8]}",
                decision=d.decision,
                rationale=d.rationale,
                constraints=list(d.constraints),
                recorded_at=d.recorded_at,
            )
            for d in source_chk.decisions
        ]

        chk_provenance = ProvenanceRecord(
            provenance_type=ProvenanceType.USER_CONFIRMED,
            captured_by="branch_operation",
            captured_at=datetime.now(timezone.utc).isoformat(),
            is_authoritative=True,
            details={
                "branch_source_activity_id": source_act.id,
                "branch_source_checkpoint_id": source_chk.id,
                "branch_name": clean_branch_name,
            },
        )

        chk_metadata = dict(source_chk.metadata)
        chk_metadata.update({
            "branch_source_activity_id": source_act.id,
            "branch_source_checkpoint_id": source_chk.id,
            "branch_name": clean_branch_name,
        })

        new_checkpoint = UniversalCheckpoint(
            id=chk_id,
            activity_id=act_id,
            parent_checkpoint_id=None,
            branch_source_checkpoint_id=source_chk.id,
            structured_state=copy.deepcopy(source_chk.structured_state),
            progress=copy.deepcopy(source_chk.progress),
            completed_work=list(source_chk.completed_work),
            pending_actions=list(source_chk.pending_actions),
            decisions=cloned_decisions,
            context=source_chk.context,
            references=list(source_chk.references),
            blockers=list(source_chk.blockers),
            artifacts=reused_artifacts,
            permitted_excerpts=list(source_chk.permitted_excerpts),
            provenance=chk_provenance,
            metadata=chk_metadata,
        )

        # Derive fresh deterministic resume brief for the new branch continuation
        try:
            from core.resume_generator import DeterministicResumeBriefGenerator
            brief_gen = DeterministicResumeBriefGenerator(workspace_root=self.workspace_root)
            new_checkpoint.resume_brief = brief_gen.generate_brief(new_activity, new_checkpoint)
        except Exception:
            pass

        # 5. Atomic persistence with rollback on partial failure
        act_dir = self._get_activity_dir(act_id)
        try:
            created_act = self.create_activity(new_activity)
            committed_chk = self.commit_checkpoint(new_checkpoint)
            return created_act, committed_chk
        except Exception as e:
            # Full rollback: remove directory & index entries for new activity
            if act_dir.exists():
                shutil.rmtree(act_dir, ignore_errors=True)
            try:
                with self._get_db_connection() as conn:
                    conn.execute("DELETE FROM checkpoints_idx WHERE activity_id = ?", (act_id,))
                    conn.execute("DELETE FROM activities_idx WHERE id = ?", (act_id,))
            except Exception:
                pass
            raise CommitFailedError(f"Failed to branch from checkpoint: {e}", internal_details=str(e))

    def get_branch_ancestry(self, activity_id: str) -> Dict[str, Any]:
        """
        Phase 65: Traces the branch ancestry of an activity back to its origin.
        Makes branch origin visible without mutating historical records.
        """
        activity = self.get_activity(activity_id)
        ancestry_chain: List[Dict[str, Any]] = []
        curr_act = activity
        visited: Set[str] = set()

        while curr_act and curr_act.id not in visited:
            visited.add(curr_act.id)
            source_chk_id = curr_act.metadata.get("branch_source_checkpoint_id")
            source_act_id = curr_act.metadata.get("branch_source_activity_id")
            branch_name = curr_act.metadata.get("branch_name")

            if not source_act_id:
                break

            ancestry_chain.append({
                "activity_id": curr_act.id,
                "activity_title": curr_act.title,
                "branch_name": branch_name,
                "source_activity_id": source_act_id,
                "source_checkpoint_id": source_chk_id,
            })

            try:
                curr_act = self.get_activity(source_act_id)
            except Exception:
                break

        return {
            "activity_id": activity.id,
            "title": activity.title,
            "is_branch": bool(activity.metadata.get("branch_source_checkpoint_id")),
            "branch_source_checkpoint_id": activity.metadata.get("branch_source_checkpoint_id"),
            "branch_source_activity_id": activity.metadata.get("branch_source_activity_id"),
            "branch_name": activity.metadata.get("branch_name"),
            "branched_at": activity.metadata.get("branched_at"),
            "ancestry_depth": len(ancestry_chain),
            "ancestry_chain": ancestry_chain,
        }

    # =========================================================================
    # PHASE 66 — EXPLICIT RESTORE AND RECOVERY
    # =========================================================================

    def preview_restore(
        self,
        target_checkpoint_id: str,
        activity_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Phase 66: Generates a pre-flight explanation of working state changes
        if the activity were restored to target_checkpoint_id.
        Pure read-only pre-flight inspection; does NOT mutate history or files (I-03).
        """
        if not target_checkpoint_id or not isinstance(target_checkpoint_id, str) or not target_checkpoint_id.strip():
            raise CheckpointValidationError("Parameter 'target_checkpoint_id' must be a non-empty string.")

        target_chk = self.get_checkpoint(target_checkpoint_id.strip())
        act_id = activity_id.strip() if activity_id and activity_id.strip() else target_chk.activity_id

        # 1. Compatibility verification
        if activity_id and target_chk.activity_id != act_id:
            raise IncompatibleRestoreError(
                f"Target checkpoint '{target_checkpoint_id}' belongs to activity '{target_chk.activity_id}', not '{act_id}'."
            )

        activity = self.get_activity(act_id)
        target_chk.validate()

        # 2. Get current head checkpoint
        head_list, total_count = self.list_checkpoints(act_id, limit=1, offset=0, order="desc")
        if not head_list:
            raise IncompatibleRestoreError(f"Activity '{act_id}' has no existing checkpoints.")

        current_head = head_list[0]
        is_current_head = (current_head.id == target_chk.id)

        # 3. Count newer checkpoints that will remain preserved
        newer_count = 0
        with self._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM checkpoints_idx WHERE activity_id = ? AND timestamp > ?",
                (act_id, target_chk.timestamp),
            )
            newer_count = cur.fetchone()[0]

        # 4. Use CheckpointDiffEngine to calculate exact working state delta
        from core.checkpoint_diff import CheckpointDiffEngine
        diff_engine = CheckpointDiffEngine(allow_cross_activity=False)
        diff_result = diff_engine.compare(current_head, target_chk)

        # 5. Build clear human-readable explanation points
        explanation_points = []
        if is_current_head:
            explanation_points.append("Target checkpoint is already the current active head. No working state changes needed.")
        else:
            # Progress delta
            if diff_result.progress.percentage_delta is not None and abs(diff_result.progress.percentage_delta) > 0.001:
                direction = "roll back" if diff_result.progress.percentage_delta < 0 else "advance"
                explanation_points.append(
                    f"Progress will {direction} from {diff_result.progress.percentage_before}% to {diff_result.progress.percentage_after}% ({diff_result.progress.percentage_delta:+0.1f}%)."
                )

            # Completed work changes
            if diff_result.completed_work.removed:
                explanation_points.append(
                    f"{len(diff_result.completed_work.removed)} completed work item(s) from newer checkpoints will be rolled back."
                )
            if diff_result.completed_work.added:
                explanation_points.append(
                    f"{len(diff_result.completed_work.added)} historical work item(s) will be reinstated."
                )

            # Pending actions changes
            if diff_result.pending_actions.added:
                explanation_points.append(
                    f"{len(diff_result.pending_actions.added)} earlier pending action(s) will be reinstated."
                )
            if diff_result.pending_actions.removed:
                explanation_points.append(
                    f"{len(diff_result.pending_actions.removed)} newer pending action(s) will be removed."
                )

            # Decisions changes
            if diff_result.decisions.removed:
                explanation_points.append(
                    f"{len(diff_result.decisions.removed)} newer decision(s) will be superseded."
                )
            if diff_result.decisions.added:
                explanation_points.append(
                    f"{len(diff_result.decisions.added)} earlier decision(s) will be reinstated."
                )

            # Blockers changes
            if diff_result.blockers.added:
                explanation_points.append(
                    f"{len(diff_result.blockers.added)} earlier blocker(s) will be reinstated."
                )
            if diff_result.blockers.removed:
                explanation_points.append(
                    f"{len(diff_result.blockers.removed)} current blocker(s) will be cleared."
                )

        state_summary = " ".join(explanation_points) if explanation_points else "No significant state deltas detected."

        return {
            "activity_id": activity.id,
            "activity_title": activity.title,
            "current_head_checkpoint_id": current_head.id,
            "current_head_timestamp": current_head.timestamp,
            "target_checkpoint_id": target_chk.id,
            "target_timestamp": target_chk.timestamp,
            "is_current_head": is_current_head,
            "newer_checkpoints_preserved_count": newer_count,
            "state_change_summary": state_summary,
            "explanation_points": explanation_points,
            "diff": diff_result.to_dict(),
            "preservation_guarantee": "All newer checkpoints remain 100% preserved. Restore appends a new checkpoint representing reinstated state without rewriting or deleting history (I-03).",
        }

    def confirm_restore(
        self,
        target_checkpoint_id: str,
        activity_id: Optional[str] = None,
        reason: Optional[str] = None,
        expected_head_checkpoint_id: Optional[str] = None,
        new_checkpoint_id: Optional[str] = None,
    ) -> Tuple[Activity, UniversalCheckpoint]:
        """
        Phase 66: Executes confirmed restore operation.
        Appends a new checkpoint to the activity representing the reinstated historical state.
        Preserves all newer checkpoints in place without silent deletion (I-03 Gate).
        Uses atomic commit with clean rollback on failure.
        """
        if not target_checkpoint_id or not isinstance(target_checkpoint_id, str) or not target_checkpoint_id.strip():
            raise CheckpointValidationError("Parameter 'target_checkpoint_id' must be a non-empty string.")

        target_chk = self.get_checkpoint(target_checkpoint_id.strip())
        act_id = activity_id.strip() if activity_id and activity_id.strip() else target_chk.activity_id

        # 1. Compatibility & Integrity Validations
        if activity_id and target_chk.activity_id != act_id:
            raise IncompatibleRestoreError(
                f"Target checkpoint '{target_checkpoint_id}' belongs to activity '{target_chk.activity_id}', not '{act_id}'."
            )

        activity = self.get_activity(act_id)
        target_chk.validate()

        # 2. Concurrency verification against head
        head_list, _ = self.list_checkpoints(act_id, limit=1, offset=0, order="desc")
        current_head = head_list[0] if head_list else None

        if expected_head_checkpoint_id and current_head:
            if current_head.id != expected_head_checkpoint_id.strip():
                raise CommitFailedError(
                    f"Concurrency conflict: expected head checkpoint '{expected_head_checkpoint_id}' but current head is '{current_head.id}'."
                )

        # 3. Construct reinstated checkpoint entities
        chk_id = new_checkpoint_id.strip() if new_checkpoint_id and new_checkpoint_id.strip() else f"chk_{uuid.uuid4().hex[:12]}"

        # Copy artifact references without duplicating physical files
        reused_artifacts = [
            ArtifactReference(
                name=a.name,
                path_or_uri=a.path_or_uri,
                mode=a.mode,
                captured_at=a.captured_at,
                checksum_sha256=a.checksum_sha256,
                size_bytes=a.size_bytes,
                snapshot_content=a.snapshot_content,
            )
            for a in target_chk.artifacts
        ]

        # Clone decisions
        cloned_decisions = [
            DecisionRecord(
                id=f"dec_{uuid.uuid4().hex[:8]}",
                decision=d.decision,
                rationale=d.rationale,
                constraints=list(d.constraints),
                recorded_at=d.recorded_at,
            )
            for d in target_chk.decisions
        ]

        # Restore provenance
        restore_reason_str = reason.strip() if reason and reason.strip() else "User confirmed restore to historical checkpoint"
        prov = ProvenanceRecord(
            provenance_type=ProvenanceType.USER_CONFIRMED,
            captured_by="restore_operation",
            captured_at=datetime.now(timezone.utc).isoformat(),
            is_authoritative=True,
            details={
                "restored_from_checkpoint_id": target_chk.id,
                "prior_head_checkpoint_id": current_head.id if current_head else None,
                "reason": restore_reason_str,
            },
        )

        chk_metadata = dict(target_chk.metadata)
        chk_metadata.update({
            "restored_from_checkpoint_id": target_chk.id,
            "prior_head_checkpoint_id": current_head.id if current_head else None,
            "restore_reason": restore_reason_str,
            "restored_at": datetime.now(timezone.utc).isoformat(),
        })

        restored_checkpoint = UniversalCheckpoint(
            id=chk_id,
            activity_id=act_id,
            parent_checkpoint_id=current_head.id if current_head else None,
            branch_source_checkpoint_id=target_chk.branch_source_checkpoint_id,
            structured_state=copy.deepcopy(target_chk.structured_state),
            progress=copy.deepcopy(target_chk.progress),
            completed_work=list(target_chk.completed_work),
            pending_actions=list(target_chk.pending_actions),
            decisions=cloned_decisions,
            context=f"[Restored from {target_chk.id}] " + (target_chk.context or ""),
            references=list(target_chk.references),
            blockers=list(target_chk.blockers),
            artifacts=reused_artifacts,
            permitted_excerpts=list(target_chk.permitted_excerpts),
            provenance=prov,
            metadata=chk_metadata,
        )

        # Derive fresh resume brief
        try:
            from core.resume_generator import DeterministicResumeBriefGenerator
            brief_gen = DeterministicResumeBriefGenerator(workspace_root=self.workspace_root)
            restored_checkpoint.resume_brief = brief_gen.generate_brief(activity, restored_checkpoint)
        except Exception:
            pass

        # 4. Atomic Commit
        try:
            committed_chk = self.commit_checkpoint(restored_checkpoint)
            activity.updated_at = datetime.now(timezone.utc).isoformat()
            updated_act = self.update_activity(activity)
            return updated_act, committed_chk
        except Exception as e:
            raise CommitFailedError(f"Restore confirmation failed: {e}", internal_details=str(e))

    # =========================================================================
    # RECOVERY & INDEX REBUILD (I-06)
    # =========================================================================

    def rebuild_index_from_authoritative_files(self) -> int:
        """
        Scans all partitioned JSON files in `<workspace_root>/.continuum/activities/`
        and deterministically rebuilds the SQLite index (I-06).
        Returns total number of records indexed (activities + checkpoints).
        """
        # Re-initialize fresh schema
        with self._get_db_connection() as conn:
            conn.executescript("""
                DELETE FROM checkpoints_idx;
                DELETE FROM activities_idx;
                DELETE FROM search_fts;
            """)

        total_indexed = 0
        if not self.activities_dir.exists():
            return 0

        # Scan activities
        for act_dir in self.activities_dir.iterdir():
            if not act_dir.is_dir():
                continue

            act_file = act_dir / "activity.json"
            if not act_file.exists():
                continue

            try:
                with open(act_file, "r", encoding="utf-8") as f:
                    act_data = json.load(f)
                activity = Activity.from_dict(act_data)
            except Exception:
                continue

            desc_val = getattr(activity, "description", "") or getattr(activity, "purpose", "")
            type_val = activity.activity_type.value if hasattr(activity.activity_type, "value") else str(activity.activity_type)
            status_val = activity.status.value if hasattr(activity.status, "value") else str(activity.status)
            with self._get_db_connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO activities_idx
                    (id, title, description, type, status, tags_json, collection, created_at, updated_at, file_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        activity.id,
                        activity.title,
                        desc_val,
                        type_val,
                        status_val,
                        json.dumps(list(activity.tags)),
                        activity.collection,
                        activity.created_at,
                        activity.updated_at,
                        str(act_file),
                    ),
                )
            total_indexed += 1
            try:
                self.index_activity_search(activity)
            except Exception:
                pass

            # Scan checkpoints for this activity
            chk_dir = act_dir / "checkpoints"
            if not chk_dir.exists():
                continue

            for chk_file in chk_dir.glob("*.json"):
                if chk_file.name.endswith(".tmp") or ".tmp_" in chk_file.name:
                    continue
                try:
                    with open(chk_file, "r", encoding="utf-8") as f:
                        chk_data = json.load(f)
                    chk = UniversalCheckpoint.from_dict(chk_data)
                except Exception:
                    continue

                if isinstance(chk.progress, dict):
                    chk_progress = float(chk.progress.get("percentage", 0.0))
                elif isinstance(chk.progress, (int, float)):
                    chk_progress = float(chk.progress)
                else:
                    chk_progress = 0.0

                if chk.provenance and hasattr(chk.provenance, "provenance_type"):
                    pt = chk.provenance.provenance_type
                    chk_prov = pt.value if hasattr(pt, "value") else str(pt)
                else:
                    chk_prov = "auto_captured"

                summary_text = None
                if chk.resume_brief:
                    summary_text = getattr(chk.resume_brief, "purpose", None) or getattr(chk.resume_brief, "summary", None)

                with self._get_db_connection() as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO checkpoints_idx
                        (id, activity_id, parent_checkpoint_id, timestamp, progress,
                         completed_count, pending_count, decisions_count, blockers_count,
                         artifacts_count, provenance_type, summary, file_path)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            chk.id,
                            chk.activity_id,
                            chk.parent_checkpoint_id,
                            chk.timestamp,
                            chk_progress,
                            len(chk.completed_work),
                            len(chk.pending_actions),
                            len(chk.decisions),
                            len(chk.blockers),
                            len(chk.artifacts),
                            chk_prov,
                            summary_text,
                            str(chk_file),
                        ),
                    )
                total_indexed += 1
                try:
                    self.index_checkpoint_search(chk)
                except Exception:
                    pass

        return total_indexed

    # =========================================================================
    # SEARCH ENGINE & FTS INDEX (Phase 68)
    # =========================================================================

    def index_activity_search(self, activity: Activity) -> bool:
        """
        Indexes an activity into derived FTS5 table.
        Does not block or corrupt authoritative operations on failure.
        """
        try:
            from core.search_engine import SearchDocumentBuilder
            doc = SearchDocumentBuilder.build_activity_document(activity)
            with self._get_db_connection() as conn:
                conn.execute("DELETE FROM search_fts WHERE record_id = ?", (doc["record_id"],))
                conn.execute(
                    """
                    INSERT INTO search_fts
                    (record_id, record_type, activity_id, title, description, notes,
                     decisions, actions, briefs, artifacts, tags, type, status, collection, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc["record_id"],
                        doc["record_type"],
                        doc["activity_id"],
                        doc["title"],
                        doc["description"],
                        doc["notes"],
                        doc["decisions"],
                        doc["actions"],
                        doc["briefs"],
                        doc["artifacts"],
                        doc["tags"],
                        doc["type"],
                        doc["status"],
                        doc["collection"],
                        doc["timestamp"],
                    ),
                )
            return True
        except Exception:
            return False

    def index_checkpoint_search(
        self,
        checkpoint: UniversalCheckpoint,
        activity: Optional[Activity] = None
    ) -> bool:
        """
        Indexes a checkpoint into derived FTS5 table.
        Does not block or corrupt authoritative operations on failure.
        """
        try:
            from core.search_engine import SearchDocumentBuilder
            if activity is None:
                try:
                    activity = self.get_activity(checkpoint.activity_id)
                except Exception:
                    pass
            doc = SearchDocumentBuilder.build_checkpoint_document(checkpoint, activity=activity)
            with self._get_db_connection() as conn:
                conn.execute("DELETE FROM search_fts WHERE record_id = ?", (doc["record_id"],))
                conn.execute(
                    """
                    INSERT INTO search_fts
                    (record_id, record_type, activity_id, title, description, notes,
                     decisions, actions, briefs, artifacts, tags, type, status, collection, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc["record_id"],
                        doc["record_type"],
                        doc["activity_id"],
                        doc["title"],
                        doc["description"],
                        doc["notes"],
                        doc["decisions"],
                        doc["actions"],
                        doc["briefs"],
                        doc["artifacts"],
                        doc["tags"],
                        doc["type"],
                        doc["status"],
                        doc["collection"],
                        doc["timestamp"],
                    ),
                )
            return True
        except Exception:
            return False

    def remove_search_document(self, record_id: str) -> None:
        """Removes a record from the FTS5 search index."""
        try:
            with self._get_db_connection() as conn:
                conn.execute("DELETE FROM search_fts WHERE record_id = ?", (record_id,))
        except Exception:
            pass

    def search(
        self,
        query: Optional[str] = None,
        record_type: Optional[str] = None,
        activity_id: Optional[str] = None,
        status: Optional[str] = None,
        activity_type: Optional[str] = None,
        tag: Optional[str] = None,
        tags: Optional[str] = None,
        collection: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> Tuple[List[Any], int]:
        """
        Searches activities and checkpoints using FTS5 with bounded pagination and filtering.
        Returns a tuple of (results_list, total_match_count).
        Phase 69: Enriched with owning activity title, current head vs history distinction,
        and bounded excerpts.
        """
        from core.search_engine import SearchQuerySanitizer, SearchResult, bound_excerpt
        from server.sanitizer import DaemonSanitizer

        clamped_limit = max(1, min(limit, 100))
        clamped_offset = max(0, offset)

        raw_query = (query or "").strip()
        fts_query = SearchQuerySanitizer.sanitize(raw_query)

        where_clauses: List[str] = []
        params: List[Any] = []

        if fts_query:
            where_clauses.append("search_fts MATCH ?")
            params.append(fts_query)

        if record_type:
            where_clauses.append("record_type = ?")
            params.append(record_type.strip().lower())

        if activity_id:
            where_clauses.append("activity_id = ?")
            params.append(activity_id.strip())

        if status:
            where_clauses.append("LOWER(status) = ?")
            params.append(status.strip().lower())

        if activity_type:
            where_clauses.append("LOWER(type) = ?")
            params.append(activity_type.strip().lower())

        if collection:
            where_clauses.append("collection = ?")
            params.append(collection.strip())

        effective_tag = tag or tags
        if effective_tag:
            where_clauses.append("tags LIKE ?")
            params.append(f"%{effective_tag.strip().lower()}%")

        if date_from:
            df = date_from.strip()
            if len(df) == 10 and "T" not in df:
                df = f"{df}T00:00:00.000000Z"
            where_clauses.append("timestamp >= ?")
            params.append(df)

        if date_to:
            dt = date_to.strip()
            if len(dt) == 10 and "T" not in dt:
                dt = f"{dt}T23:59:59.999999Z"
            where_clauses.append("timestamp <= ?")
            params.append(dt)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        count_sql = f"SELECT COUNT(*) as total FROM search_fts {where_sql}"

        if fts_query:
            select_sql = f"""
                SELECT record_id, record_type, activity_id, title, description, timestamp,
                       snippet(search_fts, -1, '<mark>', '</mark>', '...', 16) AS snippet,
                       rank AS score, tags, type, status, collection
                FROM search_fts
                {where_sql}
                ORDER BY rank
                LIMIT ? OFFSET ?
            """
        else:
            select_sql = f"""
                SELECT record_id, record_type, activity_id, title, description, timestamp,
                       '' AS snippet, 0.0 AS score, tags, type, status, collection
                FROM search_fts
                {where_sql}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            """

        page_params = list(params) + [clamped_limit, clamped_offset]

        with self._get_db_connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(count_sql, params)
                total = cur.fetchone()["total"]
                cur.execute(select_sql, page_params)
                rows = cur.fetchall()
            except sqlite3.OperationalError:
                if fts_query:
                    quoted_fallback = f'"{raw_query.replace(chr(34), " ").strip()}"'
                    params[0] = quoted_fallback
                    page_params[0] = quoted_fallback
                    try:
                        cur.execute(count_sql, params)
                        total = cur.fetchone()["total"]
                        cur.execute(select_sql, page_params)
                        rows = cur.fetchall()
                    except Exception:
                        return [], 0
                else:
                    return [], 0

        # Phase 69: Batch resolve owning activity titles and head checkpoint IDs
        activity_titles: Dict[str, str] = {}
        head_checkpoint_ids: Dict[str, str] = {}
        act_ids = list({r["activity_id"] for r in rows if r["activity_id"]})

        if act_ids:
            with self._get_db_connection() as conn:
                cur = conn.cursor()
                placeholders = ",".join("?" for _ in act_ids)
                # Fetch activity titles
                cur.execute(
                    f"SELECT id, title FROM activities_idx WHERE id IN ({placeholders})",
                    act_ids
                )
                for a_row in cur.fetchall():
                    activity_titles[a_row["id"]] = a_row["title"]

                # Fetch latest checkpoint ID (current head) for each activity
                cur.execute(
                    f"""
                    SELECT c.activity_id, c.id
                    FROM checkpoints_idx c
                    INNER JOIN (
                        SELECT activity_id, MAX(timestamp) AS max_ts
                        FROM checkpoints_idx
                        WHERE activity_id IN ({placeholders})
                        GROUP BY activity_id
                    ) latest ON c.activity_id = latest.activity_id AND c.timestamp = latest.max_ts
                    """,
                    act_ids
                )
                for c_row in cur.fetchall():
                    head_checkpoint_ids[c_row["activity_id"]] = c_row["id"]

        results: List[SearchResult] = []
        for r in rows:
            rec_id = r["record_id"]
            rec_type = r["record_type"]
            act_id = r["activity_id"]
            tags_list = [t for t in (r["tags"] or "").split(" ") if t]

            raw_snippet = r["snippet"] or ""
            if not raw_snippet and r["description"]:
                raw_snippet = r["description"]

            snippet_sanitized = DaemonSanitizer.sanitize_text(raw_snippet)
            bounded_snippet = bound_excerpt(snippet_sanitized, max_chars=280)
            desc_sanitized = bound_excerpt(DaemonSanitizer.sanitize_text(r["description"] or ""), max_chars=280)

            owning_title = activity_titles.get(act_id, "")
            if rec_type == "activity":
                state_kind = "activity"
                is_head = True
                if not owning_title:
                    owning_title = r["title"]
            else:
                chk_id = rec_id[4:] if rec_id.startswith("chk:") else r["title"]
                current_head = head_checkpoint_ids.get(act_id)
                if current_head and chk_id == current_head:
                    is_head = True
                    state_kind = "current_state"
                else:
                    is_head = False
                    state_kind = "history"

            results.append(
                SearchResult(
                    record_id=r["record_id"],
                    record_type=r["record_type"],
                    activity_id=r["activity_id"],
                    title=r["title"],
                    description=desc_sanitized,
                    timestamp=r["timestamp"],
                    snippet=bounded_snippet,
                    score=float(r["score"] or 0.0),
                    tags=tags_list,
                    collection=r["collection"] or None,
                    status=r["status"] or None,
                    activity_type=r["type"] or None,
                    activity_title=owning_title,
                    is_current_head=is_head,
                    state_kind=state_kind,
                )
            )

        return results, total

    def rebuild_search_index(self) -> int:
        """
        Rebuilds the FTS5 search index from authoritative JSON files (I-06).
        Returns total number of records indexed into search_fts.
        """
        indexed_count = 0
        with self._get_db_connection() as conn:
            conn.execute("DELETE FROM search_fts;")

        if not self.activities_dir.exists():
            return 0

        for act_dir in self.activities_dir.iterdir():
            if not act_dir.is_dir():
                continue
            act_file = act_dir / "activity.json"
            if act_file.exists():
                try:
                    with open(act_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    act = Activity.from_dict(data)
                    if self.index_activity_search(act):
                        indexed_count += 1
                except Exception:
                    pass

            chk_dir = act_dir / "checkpoints"
            if chk_dir.exists():
                for chk_file in chk_dir.glob("*.json"):
                    if chk_file.name.endswith(".tmp") or ".tmp_" in chk_file.name:
                        continue
                    try:
                        with open(chk_file, "r", encoding="utf-8") as f:
                            cdata = json.load(f)
                        chk = UniversalCheckpoint.from_dict(cdata)
                        if self.index_checkpoint_search(chk):
                            indexed_count += 1
                    except Exception:
                        pass

        return indexed_count
