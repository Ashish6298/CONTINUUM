"""
Project Continuum - Activity & Lifecycle Domain Model (v1.4.0)
==============================================================
Milestone 36 - Phase 53: Activity and Lifecycle Model.
Defines the core Activity entity, stable local identity, built-in/custom templates,
tags, collections, related-activity links, and strictly governed lifecycle transitions.

Invariants:
- I-01: Stable local-generated IDs across edits and renames.
- I-16: Lifecycle changes preserve history and reject/explain invalid transitions.
- Completed activities can be reopened to active.
- Archived activities remain preserved and can be restored.
- Status changes never delete historical checkpoints or rewrite history.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional, Set, Union
import uuid

from core.enums import ActivityStatus, ActivityType


class InvalidStatusTransitionError(ValueError):
    """Raised when an illegal or unsupported status lifecycle transition is attempted."""
    pass


class ActivityValidationError(ValueError):
    """Raised when an Activity attribute fails validation (e.g. empty title, malformed ID)."""
    pass


# Strict lifecycle state machine
VALID_STATUS_TRANSITIONS: Dict[ActivityStatus, Set[ActivityStatus]] = {
    ActivityStatus.ACTIVE: {ActivityStatus.PAUSED, ActivityStatus.COMPLETED, ActivityStatus.ARCHIVED},
    ActivityStatus.PAUSED: {ActivityStatus.ACTIVE, ActivityStatus.COMPLETED, ActivityStatus.ARCHIVED},
    ActivityStatus.COMPLETED: {ActivityStatus.ACTIVE, ActivityStatus.ARCHIVED},
    ActivityStatus.ARCHIVED: {ActivityStatus.ACTIVE, ActivityStatus.PAUSED},
}

# Built-in activity templates
ACTIVITY_TEMPLATES: Dict[Union[ActivityType, str], Dict[str, Any]] = {
    ActivityType.CODING: {
        "title": "Coding Session",
        "description": "Software implementation, debugging, or architecture refactoring session.",
        "tags": ["coding", "development"],
        "default_steps": ["Plan architecture", "Implement code changes", "Run tests and verify"],
    },
    ActivityType.STUDY: {
        "title": "Study Session",
        "description": "Learning session for concepts, research papers, tutorials, or documentation.",
        "tags": ["study", "learning"],
        "default_steps": ["Read materials", "Take structured notes", "Synthesize key takeaways"],
    },
    ActivityType.RESEARCH: {
        "title": "Research Project",
        "description": "Investigation into technical approaches, libraries, benchmarks, or trade-offs.",
        "tags": ["research", "investigation"],
        "default_steps": ["Define research questions", "Collect empirical evidence", "Document findings"],
    },
    ActivityType.WRITING: {
        "title": "Writing Project",
        "description": "Documentation, technical specification, article, or narrative writing.",
        "tags": ["writing", "documentation"],
        "default_steps": ["Draft outline", "Write content", "Review and revise"],
    },
    ActivityType.WORK_TASK: {
        "title": "Work Task",
        "description": "Operational, project management, or organizational deliverable task.",
        "tags": ["work", "task"],
        "default_steps": ["Identify requirements", "Execute tasks", "Review deliverables"],
    },
    ActivityType.AI_AGENT: {
        "title": "AI-Agent Session",
        "description": "Guided or autonomous AI coding agent execution session.",
        "tags": ["ai_agent", "automation"],
        "default_steps": ["Specify agent goal", "Review intermediate checkpoints", "Validate final output"],
    },
}


@dataclass
class Activity:
    """
    Represents an ongoing unit of work across human, AI agent, or coding workflows.
    Maintains a stable unique identity across renames, updates, and transitions.
    """
    id: str
    title: str
    description: str = ""
    activity_type: str = ActivityType.CODING.value
    status: ActivityStatus = ActivityStatus.ACTIVE
    tags: List[str] = field(default_factory=list)
    collection: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    related_activity_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Validate ID
        if not self.id or not isinstance(self.id, str) or not self.id.strip():
            raise ActivityValidationError("Activity 'id' must be a non-empty string.")
        self.id = self.id.strip()

        # Validate title
        if not self.title or not isinstance(self.title, str) or not self.title.strip():
            raise ActivityValidationError("Activity 'title' must be a non-empty string.")
        self.title = self.title.strip()

        # Ensure status is enum
        if isinstance(self.status, str):
            try:
                self.status = ActivityStatus(self.status.lower())
            except ValueError:
                raise ActivityValidationError(f"Invalid Activity status '{self.status}'. Must be one of {[s.value for s in ActivityStatus]}")

        # Normalize activity_type
        if isinstance(self.activity_type, ActivityType):
            self.activity_type = self.activity_type.value
        elif not isinstance(self.activity_type, str) or not self.activity_type.strip():
            self.activity_type = ActivityType.CUSTOM.value
        else:
            self.activity_type = self.activity_type.strip().lower()

        # Normalize tags (unique, trimmed, lowercase)
        cleaned_tags = []
        for t in self.tags:
            if isinstance(t, str) and t.strip():
                clean_t = t.strip().lower()
                if clean_t not in cleaned_tags:
                    cleaned_tags.append(clean_t)
        self.tags = cleaned_tags

        # Normalize collection
        if self.collection:
            self.collection = self.collection.strip()

        # Normalize related_activity_ids (unique, omit self)
        cleaned_related = []
        for rid in self.related_activity_ids:
            if isinstance(rid, str) and rid.strip() and rid.strip() != self.id:
                clean_rid = rid.strip()
                if clean_rid not in cleaned_related:
                    cleaned_related.append(clean_rid)
        self.related_activity_ids = cleaned_related

    def transition_to(self, target_status: Union[ActivityStatus, str]) -> None:
        """
        Executes a validated lifecycle status transition.
        Enforces state machine invariants and updates updated_at.
        """
        if isinstance(target_status, str):
            try:
                target_status = ActivityStatus(target_status.lower())
            except ValueError:
                raise InvalidStatusTransitionError(f"Target status '{target_status}' is not a valid ActivityStatus.")

        if target_status == self.status:
            # Idempotent no-op
            return

        valid_next_statuses = VALID_STATUS_TRANSITIONS.get(self.status, set())
        if target_status not in valid_next_statuses:
            allowed_names = [s.value for s in valid_next_statuses]
            raise InvalidStatusTransitionError(
                f"Cannot transition activity '{self.id}' from '{self.status.value}' to '{target_status.value}'. "
                f"Permitted transitions from '{self.status.value}' are: {allowed_names}."
            )

        self.status = target_status
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def pause(self) -> None:
        """Pauses active activity."""
        self.transition_to(ActivityStatus.PAUSED)

    def resume(self) -> None:
        """Resumes paused or archived activity back to active."""
        self.transition_to(ActivityStatus.ACTIVE)

    def complete(self) -> None:
        """Marks activity as completed."""
        self.transition_to(ActivityStatus.COMPLETED)

    def reopen(self) -> None:
        """Reopens completed activity back to active (I-16)."""
        self.transition_to(ActivityStatus.ACTIVE)

    def archive(self) -> None:
        """Archives activity for long-term safe preservation."""
        self.transition_to(ActivityStatus.ARCHIVED)

    def restore_from_archive(self, target_status: ActivityStatus = ActivityStatus.ACTIVE) -> None:
        """Restores an archived activity to active or paused without losing any history."""
        if self.status != ActivityStatus.ARCHIVED:
            raise InvalidStatusTransitionError(f"Cannot restore from archive: activity status is '{self.status.value}', not 'archived'.")
        if target_status not in {ActivityStatus.ACTIVE, ActivityStatus.PAUSED}:
            raise InvalidStatusTransitionError(f"Archived activity can only be restored to 'active' or 'paused', not '{target_status.value}'.")
        self.transition_to(target_status)

    def update_details(
        self,
        title: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        collection: Optional[str] = None,
        activity_type: Optional[Union[ActivityType, str]] = None
    ) -> None:
        """
        Updates editable metadata while strictly preserving the stable ID (I-01).
        """
        changed = False

        if title is not None:
            clean_title = title.strip()
            if not clean_title:
                raise ActivityValidationError("Activity title cannot be empty.")
            if clean_title != self.title:
                self.title = clean_title
                changed = True

        if description is not None and description != self.description:
            self.description = description
            changed = True

        if tags is not None:
            clean_tags = []
            for t in tags:
                if isinstance(t, str) and t.strip():
                    clean_t = t.strip().lower()
                    if clean_t not in clean_tags:
                        clean_tags.append(clean_t)
            if clean_tags != self.tags:
                self.tags = clean_tags
                changed = True

        if collection is not None:
            clean_col = collection.strip() if collection else None
            if clean_col != self.collection:
                self.collection = clean_col
                changed = True

        if activity_type is not None:
            type_str = activity_type.value if isinstance(activity_type, ActivityType) else str(activity_type).strip().lower()
            if type_str != self.activity_type:
                self.activity_type = type_str
                changed = True

        if changed:
            self.updated_at = datetime.now(timezone.utc).isoformat()

    def link_related_activity(self, activity_id: str) -> None:
        """Links another activity without merging histories (I-01, I-16)."""
        clean_id = activity_id.strip()
        if not clean_id or clean_id == self.id:
            return
        if clean_id not in self.related_activity_ids:
            self.related_activity_ids.append(clean_id)
            self.updated_at = datetime.now(timezone.utc).isoformat()

    def unlink_related_activity(self, activity_id: str) -> None:
        """Unlinks a previously related activity."""
        clean_id = activity_id.strip()
        if clean_id in self.related_activity_ids:
            self.related_activity_ids.remove(clean_id)
            self.updated_at = datetime.now(timezone.utc).isoformat()

    @property
    def is_custom_type(self) -> bool:
        """Returns True if the activity uses a custom type outside standard templates."""
        return self.activity_type not in [t.value for t in ActivityType]

    def to_dict(self) -> Dict[str, Any]:
        """Converts Activity to a validated serializable dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "activity_type": self.activity_type,
            "status": self.status.value,
            "tags": list(self.tags),
            "collection": self.collection,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "related_activity_ids": list(self.related_activity_ids),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Activity":
        """Reconstructs an Activity instance from a dictionary."""
        return cls(
            id=data["id"],
            title=data["title"],
            description=data.get("description", ""),
            activity_type=data.get("activity_type", ActivityType.CODING.value),
            status=ActivityStatus(data.get("status", ActivityStatus.ACTIVE.value)),
            tags=data.get("tags", []),
            collection=data.get("collection"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            related_activity_ids=data.get("related_activity_ids", []),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def create_blank(
        cls,
        title: str = "Untitled Activity",
        activity_type: Union[ActivityType, str] = ActivityType.CODING,
        description: str = "",
        collection: Optional[str] = None,
        tags: Optional[List[str]] = None,
        custom_id: Optional[str] = None
    ) -> "Activity":
        """Factory creating a new blank activity with a stable local identity."""
        act_id = custom_id or f"act_{uuid.uuid4().hex[:12]}"
        type_str = activity_type.value if isinstance(activity_type, ActivityType) else str(activity_type)
        return cls(
            id=act_id,
            title=title,
            description=description,
            activity_type=type_str,
            status=ActivityStatus.ACTIVE,
            tags=tags or [],
            collection=collection,
        )

    @classmethod
    def create_from_template(
        cls,
        template_type: Union[ActivityType, str],
        title: Optional[str] = None,
        collection: Optional[str] = None,
        custom_tags: Optional[List[str]] = None,
        custom_id: Optional[str] = None
    ) -> "Activity":
        """Factory initializing an activity pre-populated from a built-in template."""
        key = template_type if isinstance(template_type, ActivityType) else template_type.lower()
        tpl = ACTIVITY_TEMPLATES.get(key)
        if not tpl:
            # Fall back to custom template
            tpl = {
                "title": f"{str(template_type).title()} Session",
                "description": f"Custom {template_type} session.",
                "tags": [str(template_type).lower()],
                "default_steps": [],
            }

        act_title = title or tpl["title"]
        merged_tags = list(tpl.get("tags", []))
        if custom_tags:
            for ct in custom_tags:
                if ct not in merged_tags:
                    merged_tags.append(ct)

        type_str = template_type.value if isinstance(template_type, ActivityType) else str(template_type).lower()
        act = cls.create_blank(
            title=act_title,
            activity_type=type_str,
            description=tpl.get("description", ""),
            collection=collection,
            tags=merged_tags,
            custom_id=custom_id
        )
        if tpl.get("default_steps"):
            act.metadata["template_steps"] = tpl["default_steps"]

        return act
