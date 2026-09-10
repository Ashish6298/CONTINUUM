"""
Project Continuum - State Graph Models & Validation
===================================================
Milestone 4 - Phase 9: State Graph (DAG) Construction.
Defines graph statistics, topology validation results, and traversal types.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class GraphValidationResult:
    """Outcome of DAG structure and integrity verification."""
    is_valid: bool
    cycles_detected: List[List[str]] = field(default_factory=list)
    missing_endpoint_references: List[str] = field(default_factory=list)
    orphan_node_ids: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphValidationResult":
        return cls(**data)


@dataclass
class GraphStats:
    """Summary metrics of the project's Canonical State Graph."""
    total_nodes: int = 0
    total_edges: int = 0
    nodes_by_type: Dict[str, int] = field(default_factory=dict)
    edges_by_relation: Dict[str, int] = field(default_factory=dict)
    root_node_ids: List[str] = field(default_factory=list)
    leaf_node_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphStats":
        return cls(**data)
