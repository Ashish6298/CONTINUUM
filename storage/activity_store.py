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

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from core.activity import Activity, ActivityStatus, ActivityType, ActivityValidationError, InvalidStatusTransitionError
from core.checkpoint import UniversalCheckpoint, CheckpointValidationError
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

                CREATE INDEX IF NOT EXISTS idx_chk_act_ts ON checkpoints_idx(activity_id, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_chk_parent ON checkpoints_idx(parent_checkpoint_id);
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

        return activity

    def list_activities(
        self,
        status: Optional[ActivityStatus] = None,
        activity_type: Optional[ActivityType] = None,
        tag: Optional[str] = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        offset: int = 0,
    ) -> Tuple[List[Activity], int]:
        """
        Lists activities with bounded pagination (I-17) and optional filtering.
        Returns a tuple of (items_page, total_matching_count).
        """
        clamped_limit = max(1, min(limit, self.MAX_PAGE_LIMIT))
        clamped_offset = max(0, offset)

        query = "SELECT id, file_path FROM activities_idx WHERE 1=1"
        count_query = "SELECT COUNT(*) FROM activities_idx WHERE 1=1"
        params: List[Any] = []

        if status:
            query += " AND status = ?"
            count_query += " AND status = ?"
            params.append(status.value)

        if activity_type:
            query += " AND type = ?"
            count_query += " AND type = ?"
            params.append(activity_type.value)

        if tag:
            query += " AND tags_json LIKE ?"
            count_query += " AND tags_json LIKE ?"
            params.append(f'%"{tag}"%')

        with self._get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(count_query, params)
            total_count = cursor.fetchone()[0]

            query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
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
    ) -> Tuple[List[UniversalCheckpoint], int]:
        """
        Lists checkpoints for an activity ordered by timestamp descending.
        Enforces bounded pagination (I-17).
        """
        # Verify activity exists
        if not self._get_activity_file(activity_id).exists():
            raise ActivityNotFoundError(activity_id)

        clamped_limit = max(1, min(limit, self.MAX_PAGE_LIMIT))
        clamped_offset = max(0, offset)

        with self._get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM checkpoints_idx WHERE activity_id = ?", (activity_id,))
            total_count = cur.fetchone()[0]

            cur.execute(
                """
                SELECT id FROM checkpoints_idx
                WHERE activity_id = ?
                ORDER BY timestamp DESC
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

        return total_indexed
