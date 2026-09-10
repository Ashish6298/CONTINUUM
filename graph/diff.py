"""
Project Continuum - Graph Comparison & Semantic Diff Engine
===========================================================
Milestone 4 - Phase 11: Graph Persistence, Querying & Visualization.
Compares two graph snapshots or StateGraphManager instances to compute fine-grained diffs.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set, Tuple

from graph.snapshot import GraphSnapshot


@dataclass
class NodeDelta:
    """Detailed attribute changes for a modified graph node."""
    old_status: Optional[str] = None
    new_status: Optional[str] = None
    old_confidence: Optional[float] = None
    new_confidence: Optional[float] = None
    old_evidence_count: int = 0
    new_evidence_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GraphDiff:
    """
    Semantic difference between two graph snapshots (Baseline -> Target).
    """
    baseline_id: str
    target_id: str
    added_nodes: List[str] = field(default_factory=list)
    removed_nodes: List[str] = field(default_factory=list)
    modified_nodes: Dict[str, NodeDelta] = field(default_factory=dict)
    added_edges: List[Dict[str, str]] = field(default_factory=list)
    removed_edges: List[Dict[str, str]] = field(default_factory=list)
    has_changes: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "baseline_id": self.baseline_id,
            "target_id": self.target_id,
            "has_changes": self.has_changes,
            "added_nodes": self.added_nodes,
            "removed_nodes": self.removed_nodes,
            "modified_nodes": {k: v.to_dict() for k, v in self.modified_nodes.items()},
            "added_edges": self.added_edges,
            "removed_edges": self.removed_edges,
        }

    @classmethod
    def compare(cls, snap_a: GraphSnapshot, snap_b: GraphSnapshot) -> "GraphDiff":
        """
        Computes the semantic delta from snap_a to snap_b.
        """
        nodes_a = {n["id"]: n for n in snap_a.nodes}
        nodes_b = {n["id"]: n for n in snap_b.nodes}

        ids_a = set(nodes_a.keys())
        ids_b = set(nodes_b.keys())

        added_node_ids = sorted(list(ids_b - ids_a))
        removed_node_ids = sorted(list(ids_a - ids_b))
        common_node_ids = ids_a & ids_b

        modified_nodes: Dict[str, NodeDelta] = {}
        for nid in sorted(list(common_node_ids)):
            na = nodes_a[nid]
            nb = nodes_b[nid]

            stat_changed = na.get("status") != nb.get("status")
            conf_changed = na.get("confidence_score") != nb.get("confidence_score")
            ev_changed = len(na.get("evidence_ids", [])) != len(nb.get("evidence_ids", []))

            if stat_changed or conf_changed or ev_changed:
                modified_nodes[nid] = NodeDelta(
                    old_status=na.get("status"),
                    new_status=nb.get("status"),
                    old_confidence=na.get("confidence_score"),
                    new_confidence=nb.get("confidence_score"),
                    old_evidence_count=len(na.get("evidence_ids", [])),
                    new_evidence_count=len(nb.get("evidence_ids", []))
                )

        # Compare edges
        edges_a = {(e["source_id"], e["target_id"], e["relation"]) for e in snap_a.edges}
        edges_b = {(e["source_id"], e["target_id"], e["relation"]) for e in snap_b.edges}

        added_edges_raw = edges_b - edges_a
        removed_edges_raw = edges_a - edges_b

        added_edges = [{"source_id": s, "target_id": t, "relation": r} for s, t, r in sorted(list(added_edges_raw))]
        removed_edges = [{"source_id": s, "target_id": t, "relation": r} for s, t, r in sorted(list(removed_edges_raw))]

        has_changes = bool(added_node_ids or removed_node_ids or modified_nodes or added_edges or removed_edges)

        return cls(
            baseline_id=snap_a.snapshot_id,
            target_id=snap_b.snapshot_id,
            added_nodes=added_node_ids,
            removed_nodes=removed_node_ids,
            modified_nodes=modified_nodes,
            added_edges=added_edges,
            removed_edges=removed_edges,
            has_changes=has_changes
        )
