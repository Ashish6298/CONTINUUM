"""
Project Continuum - Canonical State Serializer & Deserializer
============================================================
Handles deterministic JSON round-trip serialization, file persistence,
integrity checks, and schema validation.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

from core.state_models import CanonicalProjectState
from core.schema import validate_canonical_state_dict


class StateSerializationError(Exception):
    """Raised when serialization or deserialization fails."""
    pass


class StateValidationError(Exception):
    """Raised when a state object violates schema contracts."""
    pass


class CanonicalStateSerializer:
    """
    Serializer/Deserializer for Project Continuum Canonical Project State.
    Ensures deterministic ordering, schema validation, and strict state isolation.
    """

    @staticmethod
    def to_dict(state: CanonicalProjectState) -> Dict[str, Any]:
        """Converts CanonicalProjectState to a validated python dictionary."""
        d = state.to_dict()
        is_valid, errors = validate_canonical_state_dict(d)
        if not is_valid:
            raise StateValidationError(f"State failed schema validation: {', '.join(errors)}")
        return d

    @staticmethod
    def to_json(state: CanonicalProjectState, indent: int = 2) -> str:
        """Serializes CanonicalProjectState to a formatted JSON string with deterministic sorting."""
        state_dict = CanonicalStateSerializer.to_dict(state)
        return json.dumps(state_dict, indent=indent, sort_keys=True, ensure_ascii=False)

    @staticmethod
    def from_dict(data: Dict[str, Any], validate: bool = True) -> CanonicalProjectState:
        """Constructs and validates a CanonicalProjectState instance from a dict."""
        if validate:
            is_valid, errors = validate_canonical_state_dict(data)
            if not is_valid:
                raise StateValidationError(f"State dict failed schema validation: {', '.join(errors)}")
        return CanonicalProjectState.from_dict(data)

    @staticmethod
    def from_json(json_str: str, validate: bool = True) -> CanonicalProjectState:
        """Parses a JSON string into CanonicalProjectState."""
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise StateSerializationError(f"Malformed JSON: {e}") from e
        return CanonicalStateSerializer.from_dict(data, validate=validate)

    @staticmethod
    def save_to_file(state: CanonicalProjectState, file_path: Union[str, Path], indent: int = 2) -> None:
        """Writes canonical state JSON atomically to disk."""
        target_path = Path(file_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        json_content = CanonicalStateSerializer.to_json(state, indent=indent)
        
        # Write to temp file then rename for atomic write
        temp_file = target_path.with_suffix(f"{target_path.suffix}.tmp")
        temp_file.write_text(json_content, encoding="utf-8")
        temp_file.replace(target_path)

    @staticmethod
    def load_from_file(file_path: Union[str, Path], validate: bool = True) -> CanonicalProjectState:
        """Reads canonical state from a JSON file."""
        target_path = Path(file_path)
        if not target_path.exists():
            raise FileNotFoundError(f"State file not found: {target_path}")
        content = target_path.read_text(encoding="utf-8")
        return CanonicalStateSerializer.from_json(content, validate=validate)
