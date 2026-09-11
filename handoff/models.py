"""
Project Continuum - Handoff Models
==================================
Milestone 6 - Phase 14: Universal Handoff Package Generation.
Encapsulates standard vendor-neutral handoff packages and disk persistence.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class HandoffPackage:
    """
    Standard vendor-neutral Continuum Handoff Package.
    Contains:
    - project_state_json: machine-readable canonical state JSON string
    - project_context_md: high-level verified architectural context Markdown
    - handoff_md: focused continuation document for the next AI agent
    - evidence_files: map of relative filenames to content strings in evidence/
    """
    project_id: str
    package_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    project_state_json: str = ""
    project_context_md: str = ""
    handoff_md: str = ""
    evidence_files: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "package_timestamp": self.package_timestamp,
            "project_state_json": self.project_state_json,
            "project_context_md": self.project_context_md,
            "handoff_md": self.handoff_md,
            "evidence_files": self.evidence_files,
            "metadata": self.metadata
        }

    def save_to_directory(self, output_dir: str) -> Dict[str, str]:
        """
        Atomically saves the handoff package to output_dir with the standard structure:
        - <output_dir>/project-state.json
        - <output_dir>/project-context.md
        - <output_dir>/handoff.md
        - <output_dir>/evidence/<evidence_files>

        Returns a dictionary mapping logical keys to their written filepaths.
        """
        base_path = Path(output_dir)
        base_path.mkdir(parents=True, exist_ok=True)
        evidence_dir = base_path / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)

        written_paths: Dict[str, str] = {}

        # 1. project-state.json
        state_file = base_path / "project-state.json"
        with open(state_file, "w", encoding="utf-8") as f:
            f.write(self.project_state_json)
        written_paths["project-state.json"] = str(state_file.resolve())

        # 2. project-context.md
        context_file = base_path / "project-context.md"
        with open(context_file, "w", encoding="utf-8") as f:
            f.write(self.project_context_md)
        written_paths["project-context.md"] = str(context_file.resolve())

        # 3. handoff.md
        handoff_file = base_path / "handoff.md"
        with open(handoff_file, "w", encoding="utf-8") as f:
            f.write(self.handoff_md)
        written_paths["handoff.md"] = str(handoff_file.resolve())

        # 4. evidence files
        for rel_filename, content in self.evidence_files.items():
            ev_file = evidence_dir / rel_filename
            ev_file.parent.mkdir(parents=True, exist_ok=True)
            with open(ev_file, "w", encoding="utf-8") as f:
                f.write(content)
            written_paths[f"evidence/{rel_filename}"] = str(ev_file.resolve())

        return written_paths
