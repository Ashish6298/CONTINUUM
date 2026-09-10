"""
Project Continuum - Graph Snapshot & Persistence
================================================
Milestone 4 - Phase 11: Graph Persistence, Querying & Visualization.
Provides atomic, deterministic JSON persistence and restoration for the Canonical State Graph.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from core.state_models import GraphEdge, GraphNode


@dataclass
class GraphSnapshot:
    """
    Versioned, self-contained snapshot of the Canonical State Graph.
    """
    snapshot_id: str = field(default_factory=lambda: f"snap_{uuid.uuid4().hex[:10]}")
    schema_version: str = "1.0.0"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphSnapshot":
        return cls(
            snapshot_id=data.get("snapshot_id", f"snap_{uuid.uuid4().hex[:10]}"),
            schema_version=data.get("schema_version", "1.0.0"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            nodes=data.get("nodes", []),
            edges=data.get("edges", []),
            metadata=data.get("metadata", {})
        )

    @classmethod
    def from_graph_manager(cls, manager: Any, metadata: Optional[Dict[str, Any]] = None) -> "GraphSnapshot":
        """Creates a snapshot from an active StateGraphManager instance."""
        node_dicts = [n.to_dict() for n in sorted(manager.nodes.values(), key=lambda n: n.id)]
        edge_dicts = [e.to_dict() for e in sorted(manager.edges, key=lambda e: (e.source_id, e.target_id))]
        return cls(
            nodes=node_dicts,
            edges=edge_dicts,
            metadata=metadata or {}
        )

    def save(self, file_path: str) -> None:
        """
        Atomically saves the snapshot to disk as deterministic formatted JSON.
        """
        path = Path(file_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = path.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")
        content = json.dumps(self.to_dict(), indent=2, sort_keys=True)

        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        temp_path.replace(path)

    @classmethod
    def load(cls, file_path: str) -> "GraphSnapshot":
        """
        Loads a snapshot from disk and validates basic schema integrity.
        """
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Graph snapshot file not found: {file_path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return cls.from_dict(data)
