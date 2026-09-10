"""
Project Continuum - Vendor-Neutral Conversation Models
======================================================
Defines universal representations for conversational transcripts,
turns, roles, and tool interactions across AI models/platforms.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any, Dict, List, Optional
import uuid


class TurnRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


@dataclass
class ConversationTurn:
    """Represents an individual message turn in a conversation."""
    turn_index: int
    role: TurnRole
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    author_model: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["role"] = self.role.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationTurn":
        d = dict(data)
        d["role"] = TurnRole(d.get("role", "user"))
        return cls(**d)


@dataclass
class ConversationTranscript:
    """Vendor-neutral aggregated conversation transcript."""
    session_id: str = field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:8]}")
    platform: str = "generic"  # claude, openai, gemini, cursor, custom
    model_name: Optional[str] = None
    turns: List[ConversationTurn] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_turn(self, role: TurnRole, content: str, author_model: Optional[str] = None, **kwargs) -> ConversationTurn:
        turn = ConversationTurn(
            turn_index=len(self.turns) + 1,
            role=role,
            content=content,
            author_model=author_model or self.model_name,
            **kwargs
        )
        self.turns.append(turn)
        return turn

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "platform": self.platform,
            "model_name": self.model_name,
            "created_at": self.created_at,
            "turns": [t.to_dict() for t in self.turns],
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationTranscript":
        return cls(
            session_id=data.get("session_id", f"sess_{uuid.uuid4().hex[:8]}"),
            platform=data.get("platform", "generic"),
            model_name=data.get("model_name"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            turns=[ConversationTurn.from_dict(t) for t in data.get("turns", [])],
            metadata=data.get("metadata", {})
        )

    @classmethod
    def from_json(cls, json_str: str) -> "ConversationTranscript":
        data = json.loads(json_str)
        if isinstance(data, list):  # Array of messages format
            transcript = cls()
            for idx, msg in enumerate(data, start=1):
                role_str = msg.get("role", "user").lower()
                role = TurnRole(role_str) if role_str in [r.value for r in TurnRole] else TurnRole.USER
                transcript.turns.append(ConversationTurn(
                    turn_index=idx,
                    role=role,
                    content=msg.get("content", ""),
                    author_model=msg.get("model")
                ))
            return transcript
        return cls.from_dict(data)

    @classmethod
    def from_plain_text(cls, text: str, default_role: TurnRole = TurnRole.USER) -> "ConversationTranscript":
        """Parses plain text transcripts (e.g., 'User: ...\nAssistant: ...')."""
        transcript = cls()
        lines = text.splitlines()
        current_role = default_role
        current_buffer: List[str] = []
        turn_counter = 1

        def flush_turn():
            nonlocal turn_counter, current_buffer
            if current_buffer:
                content = "\n".join(current_buffer).strip()
                if content:
                    transcript.turns.append(ConversationTurn(
                        turn_index=turn_counter,
                        role=current_role,
                        content=content
                    ))
                    turn_counter += 1
                current_buffer = []

        for line in lines:
            lower = line.lower().strip()
            if lower.startswith("user:") or lower.startswith("human:"):
                flush_turn()
                current_role = TurnRole.USER
                current_buffer.append(line.split(":", 1)[1].strip())
            elif lower.startswith("assistant:") or lower.startswith("ai:") or lower.startswith("bot:"):
                flush_turn()
                current_role = TurnRole.ASSISTANT
                current_buffer.append(line.split(":", 1)[1].strip())
            elif lower.startswith("system:"):
                flush_turn()
                current_role = TurnRole.SYSTEM
                current_buffer.append(line.split(":", 1)[1].strip())
            else:
                current_buffer.append(line)

        flush_turn()
        return transcript
