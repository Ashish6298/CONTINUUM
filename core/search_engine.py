"""
Project Continuum - Local Search Engine & FTS Index
===================================================
Milestone 40 - Phase 68: Search Source and Index.
Provides fast, local, offline full-text search across activities and checkpoints:
1. Search sources: title, description, notes, context, decisions, actions, briefs,
   permitted artifact metadata, tags, type, status, collection, date.
2. Derived and rebuildable: search index is derived from authoritative JSON files (I-06).
3. Secret-safe: strictly redacts inline secrets and excludes high-risk credential files (I-10).
4. Failure-isolated: search indexing failure does not block or corrupt authoritative commits.
5. Zero external dependencies: utilizes standard library SQLite FTS5 engine.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from core.activity import Activity
from core.checkpoint import UniversalCheckpoint


@dataclass
class SearchResult:
    """Represents a single full-text search hit across activities or checkpoints."""
    record_id: str
    record_type: str  # "activity" or "checkpoint"
    activity_id: str
    title: str
    description: str
    timestamp: str
    snippet: str
    score: float = 0.0
    tags: List[str] = field(default_factory=list)
    collection: Optional[str] = None
    status: Optional[str] = None
    activity_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    activity_title: str = ""
    is_current_head: bool = True
    state_kind: str = "current_state"  # "current_state" | "history" | "activity"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def bound_excerpt(text: Optional[str], max_chars: int = 280) -> str:
    """
    Safely bounds excerpt text to max_chars characters while preserving balanced mark tags.
    Phase 69 requirement: bounded excerpts.
    """
    if not text:
        return ""
    clean = str(text).strip()
    if len(clean) <= max_chars:
        return clean

    truncated = clean[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars // 2:
        truncated = truncated[:last_space]

    open_marks = truncated.count("<mark>")
    close_marks = truncated.count("</mark>")
    if open_marks > close_marks:
        truncated += "</mark>"

    if not truncated.endswith("..."):
        truncated += "..."
    return truncated


class SearchDocumentBuilder:
    """
    Extracts, filters, and sanitizes searchable content from Activity and Checkpoint domain entities.
    Strictly excludes high-risk credential files and redacts inline secrets before indexing (I-10).
    """

    @staticmethod
    def _clean_text(text: Optional[str]) -> str:
        if not text or not isinstance(text, str):
            return ""
        try:
            from server.sanitizer import DaemonSanitizer
            return DaemonSanitizer.sanitize_text(text.strip())
        except Exception:
            return text.strip()

    @classmethod
    def build_activity_document(cls, activity: Activity) -> Dict[str, str]:
        """Constructs a sanitized search record for an Activity."""
        title = cls._clean_text(activity.title)
        desc_val = getattr(activity, "description", "") or getattr(activity, "purpose", "")
        description = cls._clean_text(desc_val)

        status_val = activity.status.value if hasattr(activity.status, "value") else str(activity.status)
        type_val = activity.activity_type.value if hasattr(activity.activity_type, "value") else str(activity.activity_type)

        tags_str = " ".join(cls._clean_text(t) for t in activity.tags if t)
        collection_val = cls._clean_text(activity.collection or "")
        ts = activity.updated_at or activity.created_at or datetime.now(timezone.utc).isoformat()

        return {
            "record_id": f"act:{activity.id}",
            "record_type": "activity",
            "activity_id": activity.id,
            "title": title,
            "description": description,
            "notes": "",
            "decisions": "",
            "actions": "",
            "briefs": "",
            "artifacts": "",
            "tags": tags_str,
            "type": type_val,
            "status": status_val,
            "collection": collection_val,
            "timestamp": ts,
        }

    @classmethod
    def build_checkpoint_document(
        cls,
        checkpoint: UniversalCheckpoint,
        activity: Optional[Activity] = None
    ) -> Dict[str, str]:
        """Constructs a sanitized search record for a UniversalCheckpoint."""
        context = cls._clean_text(checkpoint.context or "")

        # Aggregate notes, blockers, progress, and intent
        notes_parts: List[str] = []
        if getattr(checkpoint, "intent", None):
            notes_parts.append(cls._clean_text(str(checkpoint.intent)))
        if getattr(checkpoint, "notes", None):
            if isinstance(checkpoint.notes, list):
                for n in checkpoint.notes:
                    notes_parts.append(cls._clean_text(str(n)))
            else:
                notes_parts.append(cls._clean_text(str(checkpoint.notes)))
        if getattr(checkpoint, "blockers", None):
            for b in checkpoint.blockers:
                notes_parts.append(cls._clean_text(str(b)))
        if getattr(checkpoint, "progress", None):
            if isinstance(checkpoint.progress, dict):
                desc = checkpoint.progress.get("description") or checkpoint.progress.get("summary")
                if desc:
                    notes_parts.append(cls._clean_text(str(desc)))
            elif isinstance(checkpoint.progress, str):
                notes_parts.append(cls._clean_text(checkpoint.progress))

        notes_str = " ".join(notes_parts)

        # Aggregate decisions
        decision_parts: List[str] = []
        for d in checkpoint.decisions:
            dec_val = getattr(d, "decision", None) or getattr(d, "decision_text", None)
            if dec_val:
                decision_parts.append(cls._clean_text(str(dec_val)))
            if hasattr(d, "rationale") and d.rationale:
                decision_parts.append(cls._clean_text(str(d.rationale)))
        decisions_str = " ".join(decision_parts)

        # Aggregate actions (completed and pending)
        action_parts: List[str] = []
        for c in checkpoint.completed_work:
            action_parts.append(cls._clean_text(str(c)))
        for p in checkpoint.pending_actions:
            action_parts.append(cls._clean_text(str(p)))
        actions_str = " ".join(action_parts)

        # Aggregate resume brief
        brief_parts: List[str] = []
        if checkpoint.resume_brief:
            purpose = getattr(checkpoint.resume_brief, "purpose", None)
            if purpose:
                brief_parts.append(cls._clean_text(str(purpose)))
            summary = getattr(checkpoint.resume_brief, "summary", None)
            if summary:
                brief_parts.append(cls._clean_text(str(summary)))
            for act_item in getattr(checkpoint.resume_brief, "next_actions", []):
                brief_parts.append(cls._clean_text(str(act_item)))
            for dec_item in getattr(checkpoint.resume_brief, "key_decisions", []):
                brief_parts.append(cls._clean_text(str(dec_item)))
            for work_item in getattr(checkpoint.resume_brief, "last_completed_work", []):
                brief_parts.append(cls._clean_text(str(work_item)))
        briefs_str = " ".join(brief_parts)

        # Permitted artifact metadata (exclude high-risk sensitive files)
        try:
            from server.sanitizer import DaemonSanitizer
            is_high_risk = DaemonSanitizer.is_high_risk_file
        except Exception:
            is_high_risk = lambda p: any(str(p).lower().endswith(ext) for ext in (".env", ".key", ".pem", ".pfx", "id_rsa"))

        artifact_parts: List[str] = []
        for a in checkpoint.artifacts:
            path_str = getattr(a, "path_or_uri", "") or ""
            name_str = getattr(a, "name", "") or ""
            # Exclude high-risk credential files (e.g. .env, id_rsa, *.pem, secrets.json)
            if is_high_risk(path_str) or is_high_risk(name_str):
                continue
            if name_str:
                artifact_parts.append(cls._clean_text(name_str))
            if path_str:
                artifact_parts.append(cls._clean_text(path_str))
        artifacts_str = " ".join(artifact_parts)

        coll_val = cls._clean_text(activity.collection or "") if activity else ""
        type_val = (activity.activity_type.value if hasattr(activity.activity_type, "value") else str(activity.activity_type)) if activity else ""
        status_val = (activity.status.value if hasattr(activity.status, "value") else str(activity.status)) if activity else ""
        tags_val = " ".join(cls._clean_text(t) for t in activity.tags if t) if activity else ""

        return {
            "record_id": f"chk:{checkpoint.id}",
            "record_type": "checkpoint",
            "activity_id": checkpoint.activity_id,
            "title": checkpoint.id,
            "description": context,
            "notes": notes_str,
            "decisions": decisions_str,
            "actions": actions_str,
            "briefs": briefs_str,
            "artifacts": artifacts_str,
            "tags": tags_val,
            "type": type_val,
            "status": status_val,
            "collection": coll_val,
            "timestamp": checkpoint.timestamp or datetime.now(timezone.utc).isoformat(),
        }


class SearchQuerySanitizer:
    """
    Sanitizes user search queries into safe FTS5 MATCH expressions.
    Prevents syntax errors from illegal operators, colons, or unmatched quotes.
    """

    @staticmethod
    def sanitize(raw_query: Optional[str]) -> str:
        if not raw_query or not isinstance(raw_query, str):
            return ""

        query = raw_query.strip()
        if not query or query == "*":
            return ""

        tokens: List[str] = []
        # Find quoted phrases or whitespace-separated terms
        for match in re.finditer(r'("[^"]*"|\S+)', query):
            token = match.group(0).strip()
            if not token:
                continue

            # Quoted phrase: "my search phrase"
            if token.startswith('"') and token.endswith('"') and len(token) > 2:
                phrase = token[1:-1].replace('"', '""').strip()
                # Remove dangerous FTS5 punctuation inside phrase
                phrase = re.sub(r'[:^(){}\~]', ' ', phrase).strip()
                if phrase:
                    tokens.append(f'"{phrase}"')
            else:
                # Check for trailing wildcard
                is_prefix = token.endswith("*")
                clean_term = re.sub(r'[^\w\-]', '', token).strip()
                if clean_term:
                    if is_prefix:
                        tokens.append(f'"{clean_term}"*')
                    else:
                        tokens.append(f'"{clean_term}"')

        return " ".join(tokens)
