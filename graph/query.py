"""
Project Continuum - Graph Query Engine
======================================
Milestone 4 - Phase 11: Graph Persistence, Querying & Visualization.
Provides indexed, high-speed topological querying across the Canonical State Graph.
"""

from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

from core.enums import NodeType, RelationType, Status
from core.state_models import GraphEdge, GraphNode


class GraphQueryEngine:
    """
    Executes flexible graph queries, subgraph extractions, and impact radius calculations.
    """

    def __init__(self, manager: Any):
        self._manager = manager

    def query_by_status(self, status: Status) -> List[GraphNode]:
        """Finds all nodes matching the requested status."""
        return [n for n in self._manager.nodes.values() if n.status == status]

    def query_by_type(self, node_type: NodeType) -> List[GraphNode]:
        """Finds all nodes matching the requested NodeType."""
        return [n for n in self._manager.nodes.values() if n.node_type == node_type]

    def query_subgraph(
        self,
        seed_node_ids: List[str],
        depth: int = 2,
        direction: str = "both"  # "upstream", "downstream", "both"
    ) -> Tuple[List[GraphNode], List[GraphEdge]]:
        """
        Extracts a localized bounded subgraph around seed nodes.
        """
        included_node_ids: Set[str] = set(seed_node_ids)
        queue: deque = deque([(nid, 0) for nid in seed_node_ids if nid in self._manager.nodes])

        while queue:
            curr_id, curr_depth = queue.popleft()
            if depth >= 0 and curr_depth >= depth:
                continue

            # Upstream dependencies
            if direction in {"upstream", "both"}:
                for edge in self._manager._out_edges.get(curr_id, []):
                    target_id = edge.target_id
                    if target_id not in included_node_ids and target_id in self._manager.nodes:
                        included_node_ids.add(target_id)
                        queue.append((target_id, curr_depth + 1))

            # Downstream dependents
            if direction in {"downstream", "both"}:
                for edge in self._manager._in_edges.get(curr_id, []):
                    source_id = edge.source_id
                    if source_id not in included_node_ids and source_id in self._manager.nodes:
                        included_node_ids.add(source_id)
                        queue.append((source_id, curr_depth + 1))

        subgraph_nodes = [self._manager.nodes[nid] for nid in included_node_ids if nid in self._manager.nodes]
        subgraph_edges = [
            e for e in self._manager.edges
            if e.source_id in included_node_ids and e.target_id in included_node_ids
        ]

        return subgraph_nodes, subgraph_edges

    def query_impact_radius(self, node_id: str) -> List[str]:
        """
        Returns all downstream nodes that would be directly or transitively affected
        if `node_id` is modified or broken.
        """
        dependents = self._manager.get_dependents(node_id, recursive=True)
        return [d.id for d in dependents]

    def query_blocked_nodes(self) -> List[GraphNode]:
        """Returns all nodes currently in BLOCKED status."""
        return self.query_by_status(Status.BLOCKED)

    def query_stale_nodes(self) -> List[GraphNode]:
        """Returns all nodes currently in STALE status."""
        return self.query_by_status(Status.STALE)
