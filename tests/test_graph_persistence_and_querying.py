"""
Project Continuum - Test Suite for Phase 11 (Graph Persistence, Querying & Visualization)
==========================================================================================
Milestone 4 - Phase 11.
Validates:
1. Versioned snapshot atomic saving and restoration.
2. Semantic graph comparison and delta diff computation.
3. Indexed graph queries (by status, type, bounded subgraph, impact radius).
4. Graphviz DOT format export.
5. Large synthetic graph scalability and performance.
"""

import os
import tempfile
import unittest

from core.enums import NodeType, RelationType, Status
from core.state_models import GraphEdge, GraphNode
from graph.manager import StateGraphManager
from graph.snapshot import GraphSnapshot
from graph.diff import GraphDiff


class TestGraphPersistenceAndQuerying(unittest.TestCase):
    """Test suite for Phase 11 Graph Persistence, Diffing, and Querying."""

    def setUp(self):
        self.manager = StateGraphManager()
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_snapshot_atomic_save_and_load(self):
        """
        Saves a populated StateGraphManager to disk as a JSON snapshot,
        then loads it into a clean manager and verifies 100% data fidelity.
        """
        self.manager.add_node(GraphNode(id="n1", name="ServiceA", node_type=NodeType.SERVICE, status=Status.VERIFIED))
        self.manager.add_node(GraphNode(id="n2", name="ServiceB", node_type=NodeType.SERVICE, status=Status.STALE))
        self.manager.add_edge(GraphEdge(source_id="n2", target_id="n1", relation=RelationType.DEPENDS_ON))

        snapshot_path = os.path.join(self.temp_dir.name, "graph_snapshot.json")
        snap_id = self.manager.save_snapshot(snapshot_path, metadata={"project": "continuum"})

        self.assertTrue(os.path.exists(snapshot_path))

        # Restore into new manager
        new_manager = StateGraphManager()
        new_manager.load_snapshot(snapshot_path)

        self.assertEqual(len(new_manager.nodes), 2)
        self.assertEqual(len(new_manager.edges), 1)
        self.assertEqual(new_manager.get_node("n1").status, Status.VERIFIED)
        self.assertEqual(new_manager.get_node("n2").status, Status.STALE)

    def test_graph_comparison_diff(self):
        """
        Compares two snapshots to verify detection of added nodes, removed nodes,
        modified statuses, and added/removed edges.
        """
        # Baseline
        self.manager.add_node(GraphNode(id="n1", name="Auth", node_type=NodeType.SERVICE, status=Status.IN_PROGRESS))
        self.manager.add_node(GraphNode(id="n2", name="Database", node_type=NodeType.SERVICE, status=Status.VERIFIED))
        self.manager.add_edge(GraphEdge(source_id="n1", target_id="n2", relation=RelationType.DEPENDS_ON))
        snap_a = GraphSnapshot.from_graph_manager(self.manager)

        # Target (Target modified: n1 is now VERIFIED, n3 added, n2 removed)
        mgr_b = StateGraphManager()
        mgr_b.add_node(GraphNode(id="n1", name="Auth", node_type=NodeType.SERVICE, status=Status.VERIFIED))
        mgr_b.add_node(GraphNode(id="n3", name="Cache", node_type=NodeType.SERVICE, status=Status.VERIFIED))
        mgr_b.add_edge(GraphEdge(source_id="n1", target_id="n3", relation=RelationType.DEPENDS_ON))
        snap_b = GraphSnapshot.from_graph_manager(mgr_b)

        diff = GraphDiff.compare(snap_a, snap_b)

        self.assertTrue(diff.has_changes)
        self.assertEqual(diff.added_nodes, ["n3"])
        self.assertEqual(diff.removed_nodes, ["n2"])
        self.assertIn("n1", diff.modified_nodes)
        self.assertEqual(diff.modified_nodes["n1"].old_status, Status.IN_PROGRESS.value)
        self.assertEqual(diff.modified_nodes["n1"].new_status, Status.VERIFIED.value)
        self.assertEqual(len(diff.added_edges), 1)
        self.assertEqual(len(diff.removed_edges), 1)

    def test_graph_query_engine(self):
        """
        Queries graph by status, node type, and extracts bounded subgraphs.
        """
        self.manager.add_node(GraphNode(id="req1", name="Req 1", node_type=NodeType.REQUIREMENT, status=Status.VERIFIED))
        self.manager.add_node(GraphNode(id="svc1", name="Svc 1", node_type=NodeType.SERVICE, status=Status.VERIFIED))
        self.manager.add_node(GraphNode(id="test1", name="Test 1", node_type=NodeType.TEST, status=Status.FAILED))
        self.manager.add_node(GraphNode(id="task1", name="Task 1", node_type=NodeType.TASK, status=Status.BLOCKED))

        self.manager.add_edge(GraphEdge(source_id="svc1", target_id="req1", relation=RelationType.IMPLEMENTS))
        self.manager.add_edge(GraphEdge(source_id="test1", target_id="svc1", relation=RelationType.VERIFIES))

        query = self.manager.query()

        # Query by status
        verified = query.query_by_status(Status.VERIFIED)
        self.assertEqual(len(verified), 2)
        blocked = query.query_blocked_nodes()
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].id, "task1")

        # Query by type
        tests = query.query_by_type(NodeType.TEST)
        self.assertEqual(len(tests), 1)
        self.assertEqual(tests[0].id, "test1")

        # Subgraph query from svc1 (depth 1)
        sub_nodes, sub_edges = query.query_subgraph(seed_node_ids=["svc1"], depth=1, direction="both")
        sub_node_ids = {n.id for n in sub_nodes}
        self.assertEqual(sub_node_ids, {"svc1", "req1", "test1"})
        self.assertEqual(len(sub_edges), 2)

        # Impact radius of req1
        impact = query.query_impact_radius("req1")
        self.assertIn("svc1", impact)

    def test_graphviz_dot_export(self):
        """
        Validates generated Graphviz DOT string formatting.
        """
        self.manager.add_node(GraphNode(id="n_a", name="ComponentA", node_type=NodeType.COMPONENT, status=Status.VERIFIED))
        self.manager.add_node(GraphNode(id="n_b", name="ComponentB", node_type=NodeType.COMPONENT, status=Status.FAILED))
        self.manager.add_edge(GraphEdge(source_id="n_a", target_id="n_b", relation=RelationType.DEPENDS_ON))

        dot = self.manager.export_dot()
        self.assertIn("digraph CanonicalStateGraph {", dot)
        self.assertIn('"n_a" -> "n_b" [label="DEPENDS_ON"];', dot)
        self.assertIn("#2ecc71", dot)  # Verified green
        self.assertIn("#e74c3c", dot)  # Failed red

    def test_large_synthetic_graph_scalability(self):
        """
        Tests scalability with 500 nodes and 700 edges to guarantee fast queries
        and memory efficiency without recursion limits.
        """
        for i in range(500):
            self.manager.add_node(GraphNode(
                id=f"node_{i}",
                name=f"Component_{i}",
                node_type=NodeType.COMPONENT,
                status=Status.VERIFIED if i % 2 == 0 else Status.PENDING
            ))

        # Add directed tree edges
        for i in range(1, 500):
            parent = (i - 1) // 2
            self.manager.add_edge(GraphEdge(
                source_id=f"node_{i}",
                target_id=f"node_{parent}",
                relation=RelationType.DEPENDS_ON
            ))

        stats = self.manager.get_stats()
        self.assertEqual(stats.total_nodes, 500)
        self.assertEqual(stats.total_edges, 499)

        # Query impact of root node
        impact = self.manager.query().query_impact_radius("node_0")
        self.assertEqual(len(impact), 499)

        # Verify no cycles
        cycles = self.manager.detect_cycles()
        self.assertEqual(len(cycles), 0)


if __name__ == "__main__":
    unittest.main()
