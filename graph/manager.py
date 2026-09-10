"""
Project Continuum - State Graph (DAG) Manager
=============================================
Milestone 4 - Phase 9: State Graph (DAG) Construction.
Builds, validates, queries, and serializes the Canonical State Graph (DAG),
connecting milestones, phases, requirements, services, AST symbols, and tests
to their supporting physical evidence.
"""

from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple

from core.enums import NodeType, RelationType, Status
from core.interfaces import IStateGraphManager
from core.state_models import (
    CanonicalProjectState,
    GraphEdge,
    GraphNode,
)
from graph.models import GraphStats, GraphValidationResult


class StateGraphManager(IStateGraphManager):
    """
    Manages the Directed Acyclic Graph (DAG) of Project Continuum.
    Implements IStateGraphManager Protocol.
    """

    def __init__(self, canonical_state: Optional[CanonicalProjectState] = None):
        self._canonical_state: Optional[CanonicalProjectState] = canonical_state
        self._nodes: Dict[str, GraphNode] = {}
        self._edges: List[GraphEdge] = []
        
        # Adjacency indexes for high-speed deterministic traversal
        self._out_edges: Dict[str, List[GraphEdge]] = defaultdict(list)
        self._in_edges: Dict[str, List[GraphEdge]] = defaultdict(list)

        if canonical_state:
            for node in canonical_state.graph_nodes.values():
                self.add_node(node)
            for edge in canonical_state.graph_edges:
                self.add_edge(edge)

    @property
    def nodes(self) -> Dict[str, GraphNode]:
        return self._nodes

    @property
    def edges(self) -> List[GraphEdge]:
        return self._edges

    def add_node(self, node: GraphNode) -> None:
        """
        Adds or updates a GraphNode deterministically.
        """
        self._nodes[node.id] = node
        if self._canonical_state:
            self._canonical_state.graph_nodes[node.id] = node

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Retrieves a node by its unique ID."""
        return self._nodes.get(node_id)

    def add_edge(self, edge: GraphEdge, allow_cycle: bool = False) -> bool:
        """
        Adds a directed relationship between two existing nodes.
        If allow_cycle is False and the new edge induces a cycle, the edge is rejected.
        """
        # Prevent duplicate identical edges
        for existing in self._out_edges[edge.source_id]:
            if existing.target_id == edge.target_id and existing.relation == edge.relation:
                return True

        self._edges.append(edge)
        self._out_edges[edge.source_id].append(edge)
        self._in_edges[edge.target_id].append(edge)

        if not allow_cycle:
            cycles = self.detect_cycles()
            if cycles:
                # Rollback edge insertion
                self._edges.remove(edge)
                self._out_edges[edge.source_id].remove(edge)
                self._in_edges[edge.target_id].remove(edge)
                return False

        if self._canonical_state:
            if edge not in self._canonical_state.graph_edges:
                self._canonical_state.graph_edges.append(edge)

        return True

    def get_dependencies(self, node_id: str, recursive: bool = False) -> List[GraphNode]:
        """
        Retrieves nodes that `node_id` depends on / requires / implements / verifies.
        (Follows outgoing DEPENDS_ON, REQUIRES, IMPLEMENTS, IMPORTS, VERIFIES edges).
        """
        dependency_relations = {
            RelationType.DEPENDS_ON,
            RelationType.REQUIRES,
            RelationType.IMPLEMENTS,
            RelationType.IMPORTS,
            RelationType.VERIFIES,
        }

        visited: Set[str] = set()
        queue: deque = deque()

        for edge in self._out_edges.get(node_id, []):
            if edge.relation in dependency_relations and edge.target_id in self._nodes:
                queue.append(edge.target_id)
                visited.add(edge.target_id)

        results: List[GraphNode] = []

        while queue:
            curr_id = queue.popleft()
            node = self._nodes.get(curr_id)
            if node:
                results.append(node)

            if recursive:
                for edge in self._out_edges.get(curr_id, []):
                    if edge.relation in dependency_relations:
                        if edge.target_id not in visited and edge.target_id in self._nodes:
                            visited.add(edge.target_id)
                            queue.append(edge.target_id)

        return results

    def get_dependents(self, node_id: str, recursive: bool = False) -> List[GraphNode]:
        """
        Retrieves nodes that depend on `node_id`.
        (Follows incoming DEPENDS_ON, REQUIRES, IMPLEMENTS, IMPORTS edges).
        """
        dependency_relations = {
            RelationType.DEPENDS_ON,
            RelationType.REQUIRES,
            RelationType.IMPLEMENTS,
            RelationType.IMPORTS,
        }

        visited: Set[str] = set()
        queue: deque = deque()

        for edge in self._in_edges.get(node_id, []):
            if edge.relation in dependency_relations and edge.source_id in self._nodes:
                queue.append(edge.source_id)
                visited.add(edge.source_id)

        results: List[GraphNode] = []

        while queue:
            curr_id = queue.popleft()
            node = self._nodes.get(curr_id)
            if node:
                results.append(node)

            if recursive:
                for edge in self._in_edges.get(curr_id, []):
                    if edge.relation in dependency_relations:
                        if edge.source_id not in visited and edge.source_id in self._nodes:
                            visited.add(edge.source_id)
                            queue.append(edge.source_id)

        return results

    def detect_cycles(self) -> List[List[str]]:
        """
        Detects all elementary directed cycles in the graph using DFS recursion.
        Returns list of cycle paths (e.g. [['A', 'B', 'C', 'A']]).
        """
        visited: Dict[str, int] = {}  # 0 = unvisited, 1 = visiting (in stack), 2 = visited
        cycles: List[List[str]] = []
        path: List[str] = []

        for node_id in self._nodes:
            visited[node_id] = 0

        def dfs(u: str):
            visited[u] = 1
            path.append(u)

            for edge in self._out_edges.get(u, []):
                v = edge.target_id
                if v not in visited:
                    continue
                if visited[v] == 1:
                    # Cycle detected: extract subpath from v to end
                    cycle_start_idx = path.index(v)
                    cycle_path = path[cycle_start_idx:] + [v]
                    cycles.append(cycle_path)
                elif visited[v] == 0:
                    dfs(v)

            path.pop()
            visited[u] = 2

        for node_id in list(self._nodes.keys()):
            if visited[node_id] == 0:
                dfs(node_id)

        return cycles

    def validate_graph(self) -> GraphValidationResult:
        """
        Verifies complete topological integrity of the DAG.
        """
        cycles = self.detect_cycles()
        missing_refs: List[str] = []
        orphan_nodes: List[str] = []
        errors: List[str] = []

        # Check missing endpoints
        for edge in self._edges:
            if edge.source_id not in self._nodes:
                missing_refs.append(f"Edge source '{edge.source_id}' does not exist as a node")
            if edge.target_id not in self._nodes:
                missing_refs.append(f"Edge target '{edge.target_id}' does not exist as a node")

        # Check orphan nodes (nodes with 0 incoming and 0 outgoing edges)
        for node_id in self._nodes:
            has_in = bool(self._in_edges.get(node_id))
            has_out = bool(self._out_edges.get(node_id))
            if not has_in and not has_out:
                orphan_nodes.append(node_id)

        if cycles:
            errors.append(f"Detected {len(cycles)} circular dependency cycle(s)")
        if missing_refs:
            errors.extend(missing_refs)

        is_valid = (len(cycles) == 0 and len(missing_refs) == 0)

        return GraphValidationResult(
            is_valid=is_valid,
            cycles_detected=cycles,
            missing_endpoint_references=missing_refs,
            orphan_node_ids=orphan_nodes,
            errors=errors
        )

    def get_stats(self) -> GraphStats:
        """Calculates macro metrics of the graph."""
        nodes_by_type: Dict[str, int] = defaultdict(int)
        for n in self._nodes.values():
            nodes_by_type[n.node_type.value] += 1

        edges_by_relation: Dict[str, int] = defaultdict(int)
        for e in self._edges:
            edges_by_relation[e.relation.value] += 1

        roots = [nid for nid in self._nodes if not self._in_edges.get(nid)]
        leaves = [nid for nid in self._nodes if not self._out_edges.get(nid)]

        return GraphStats(
            total_nodes=len(self._nodes),
            total_edges=len(self._edges),
            nodes_by_type=dict(nodes_by_type),
            edges_by_relation=dict(edges_by_relation),
            root_node_ids=roots,
            leaf_node_ids=leaves
        )

    def propagate_invalidation(self, changed_node_id: str) -> List[str]:
        """
        Propagates status invalidation to all downstream dependents when a dependency changes.
        Marks affected dependents STALE (or BLOCKED if failed).
        Implements IStateGraphManager Protocol.
        """
        dependents = self.get_dependents(changed_node_id, recursive=True)
        affected_ids: List[str] = []

        for dep in dependents:
            dep.status = Status.STALE
            affected_ids.append(dep.id)

        return affected_ids

    def export_mermaid(self) -> str:
        """
        Generates Mermaid diagram representing the DAG with status and type styling.
        """
        lines = ["graph TD"]

        # Status color styles
        style_classes = [
            "    classDef verified fill:#2ecc71,stroke:#27ae60,stroke-width:2px,color:#fff;",
            "    classDef failed fill:#e74c3c,stroke:#c0392b,stroke-width:2px,color:#fff;",
            "    classDef in_progress fill:#f39c12,stroke:#d35400,stroke-width:2px,color:#fff;",
            "    classDef unverified fill:#95a5a6,stroke:#7f8c8d,stroke-width:2px,color:#fff;",
            "    classDef stale fill:#e67e22,stroke:#d35400,stroke-width:2px,color:#fff;",
            "    classDef unknown fill:#bdc3c7,stroke:#95a5a6,stroke-width:1px,color:#000;"
        ]

        # 1. Add Nodes
        for node in sorted(self._nodes.values(), key=lambda n: n.id):
            clean_id = node.id.replace("-", "_").replace(".", "_")
            label = f"{node.name} [{node.node_type.value}]<br/>({node.status.value}, {node.confidence_score:.0f}%)"
            lines.append(f'    {clean_id}["{label}"]')

        # 2. Add Edges
        relation_labels = {
            RelationType.DEPENDS_ON: "depends_on",
            RelationType.IMPLEMENTS: "implements",
            RelationType.VERIFIES: "verifies",
            RelationType.BLOCKS: "blocks",
            RelationType.IMPORTS: "imports",
            RelationType.REQUIRES: "requires",
            RelationType.INVALIDATES: "invalidates",
        }

        for edge in sorted(self._edges, key=lambda e: (e.source_id, e.target_id)):
            src = edge.source_id.replace("-", "_").replace(".", "_")
            tgt = edge.target_id.replace("-", "_").replace(".", "_")
            rel_label = relation_labels.get(edge.relation, edge.relation.value)
            lines.append(f'    {src} -->|"{rel_label}"| {tgt}')

        # 3. Add styling classes to nodes
        status_map = {
            Status.VERIFIED: "verified",
            Status.FAILED: "failed",
            Status.IN_PROGRESS: "in_progress",
            Status.UNVERIFIED: "unverified",
            Status.STALE: "stale",
            Status.UNKNOWN: "unknown"
        }

        for node in self._nodes.values():
            clean_id = node.id.replace("-", "_").replace(".", "_")
            cls_name = status_map.get(node.status, "unknown")
            lines.append(f"    class {clean_id} {cls_name};")

        lines.extend(style_classes)
        return "\n".join(lines)

    def build_from_canonical_state(self, canonical_state: CanonicalProjectState) -> None:
        """
        Constructs the DAG automatically from CanonicalProjectState entities:
        - Creates Requirement nodes from conversational state.
        - Creates Module / Symbol nodes from project state AST.
        - Creates Test nodes from test results.
        - Links Tests $\\to$ Symbols via VERIFIES.
        - Links Symbols $\\to$ Requirements via IMPLEMENTS.
        """
        self._canonical_state = canonical_state

        # 1. Add Requirement Nodes
        for req in canonical_state.conversational_state.user_requirements:
            ev_ids = [req.evidence_id] if req.evidence_id else []
            self.add_node(GraphNode(
                id=f"req_{req.id}",
                name=req.title,
                node_type=NodeType.REQUIREMENT,
                status=req.status,
                evidence_ids=ev_ids,
                metadata={"description": req.description}
            ))

        # 2. Add AST Symbol / Component Nodes
        for sym in canonical_state.project_state.symbols:
            ev_ids = [sym.evidence_id] if sym.evidence_id else []
            sym_node_id = f"sym_{sym.name}"
            self.add_node(GraphNode(
                id=sym_node_id,
                name=sym.name,
                node_type=NodeType.COMPONENT if sym.kind in {"class", "interface"} else NodeType.API,
                status=Status.VERIFIED,
                evidence_ids=ev_ids,
                metadata={"file_path": sym.file_path, "kind": sym.kind}
            ))

            # Attempt link to requirements with matching names
            for req in canonical_state.conversational_state.user_requirements:
                if req.title.lower() in sym.name.lower() or sym.name.lower() in req.title.lower():
                    self.add_edge(GraphEdge(
                        source_id=sym_node_id,
                        target_id=f"req_{req.id}",
                        relation=RelationType.IMPLEMENTS
                    ))

        # 3. Add Test Nodes and link to verified components
        for test in canonical_state.project_state.test_results:
            ev_ids = [test.evidence_id] if test.evidence_id else []
            test_node_id = f"test_{test.test_id}"
            self.add_node(GraphNode(
                id=test_node_id,
                name=test.name,
                node_type=NodeType.TEST,
                status=test.status,
                evidence_ids=ev_ids,
                metadata={"suite": test.suite, "exit_code": test.exit_code}
            ))

            # Find matching component being tested
            for sym in canonical_state.project_state.symbols:
                sym_clean = sym.name.lower().replace("service", "").replace("controller", "").replace("manager", "").replace("client", "")
                if (
                    sym.name.lower() in test.name.lower()
                    or sym.name.lower() in test.suite.lower()
                    or (sym_clean and sym_clean in test.name.lower())
                    or (sym_clean and sym_clean in test.suite.lower())
                ):
                    self.add_edge(GraphEdge(
                        source_id=test_node_id,
                        target_id=f"sym_{sym.name}",
                        relation=RelationType.VERIFIES
                    ))
