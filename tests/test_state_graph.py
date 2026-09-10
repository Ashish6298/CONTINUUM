"""
Project Continuum - Test Suite for Phase 9 (State Graph DAG Construction)
==========================================================================
Milestone 4 - Phase 9.
Validates:
1. Node and directed edge creation across multiple node types and relations.
2. Direct and recursive dependency traversal (upstream and downstream).
3. Circular dependency detection and rejection.
4. Mermaid diagram syntax and visualization generation.
5. Ingestion and graph construction from CanonicalProjectState.
6. Downstream invalidation propagation.
"""

import unittest

from core.enums import NodeType, RelationType, Status
from core.state_models import (
    AstSymbol,
    CanonicalProjectState,
    ConversationalState,
    GraphEdge,
    GraphNode,
    ProjectState,
    Requirement,
    TestResult,
)
from graph.manager import StateGraphManager


class TestStateGraph(unittest.TestCase):
    """Test suite for StateGraphManager."""

    def setUp(self):
        self.manager = StateGraphManager()

    def test_node_and_edge_creation(self):
        """
        Creates nodes of diverse types (Milestone, Phase, Requirement, Service, Test)
        and directed relations (DEPENDS_ON, IMPLEMENTS, VERIFIES).
        """
        m3 = GraphNode(id="node_m3", name="Milestone 3", node_type=NodeType.MILESTONE, status=Status.VERIFIED)
        p9 = GraphNode(id="node_p9", name="Phase 9", node_type=NodeType.PHASE, status=Status.IN_PROGRESS)
        req_auth = GraphNode(id="node_req_auth", name="JWT Auth", node_type=NodeType.REQUIREMENT, status=Status.PENDING)
        svc_auth = GraphNode(id="node_svc_auth", name="AuthService", node_type=NodeType.SERVICE, status=Status.VERIFIED)
        test_auth = GraphNode(id="node_test_auth", name="test_auth_jwt", node_type=NodeType.TEST, status=Status.VERIFIED)

        self.manager.add_node(m3)
        self.manager.add_node(p9)
        self.manager.add_node(req_auth)
        self.manager.add_node(svc_auth)
        self.manager.add_node(test_auth)

        self.assertEqual(len(self.manager.nodes), 5)

        # Connect nodes
        self.assertTrue(self.manager.add_edge(GraphEdge(source_id="node_p9", target_id="node_m3", relation=RelationType.DEPENDS_ON)))
        self.assertTrue(self.manager.add_edge(GraphEdge(source_id="node_svc_auth", target_id="node_req_auth", relation=RelationType.IMPLEMENTS)))
        self.assertTrue(self.manager.add_edge(GraphEdge(source_id="node_test_auth", target_id="node_svc_auth", relation=RelationType.VERIFIES)))

        self.assertEqual(len(self.manager.edges), 3)

        # Validate graph
        validation = self.manager.validate_graph()
        self.assertTrue(validation.is_valid)
        self.assertEqual(len(validation.cycles_detected), 0)

    def test_dependency_traversal_direct_and_recursive(self):
        """
        Builds a multi-tier dependency chain:
        App -> AuthService -> DatabasePool -> ConfigManager
        """
        nodes = [
            GraphNode(id="n_app", name="App", node_type=NodeType.COMPONENT),
            GraphNode(id="n_auth", name="AuthService", node_type=NodeType.SERVICE),
            GraphNode(id="n_db", name="DatabasePool", node_type=NodeType.SERVICE),
            GraphNode(id="n_cfg", name="ConfigManager", node_type=NodeType.MODULE)
        ]
        for n in nodes:
            self.manager.add_node(n)

        self.manager.add_edge(GraphEdge(source_id="n_app", target_id="n_auth", relation=RelationType.DEPENDS_ON))
        self.manager.add_edge(GraphEdge(source_id="n_auth", target_id="n_db", relation=RelationType.DEPENDS_ON))
        self.manager.add_edge(GraphEdge(source_id="n_db", target_id="n_cfg", relation=RelationType.DEPENDS_ON))

        # Direct dependencies of n_app
        direct_deps = self.manager.get_dependencies("n_app", recursive=False)
        self.assertEqual(len(direct_deps), 1)
        self.assertEqual(direct_deps[0].id, "n_auth")

        # Recursive upstream dependencies of n_app
        rec_deps = self.manager.get_dependencies("n_app", recursive=True)
        rec_dep_ids = [d.id for d in rec_deps]
        self.assertEqual(rec_dep_ids, ["n_auth", "n_db", "n_cfg"])

        # Downstream dependents of n_cfg (who depends on n_cfg?)
        dependents = self.manager.get_dependents("n_cfg", recursive=True)
        dependent_ids = [d.id for d in dependents]
        self.assertEqual(dependent_ids, ["n_db", "n_auth", "n_app"])

    def test_cycle_detection_and_prevention(self):
        """
        Ensures that adding a circular dependency (A -> B -> C -> A) is detected
        and rejected when allow_cycle=False.
        """
        self.manager.add_node(GraphNode(id="A", name="A", node_type=NodeType.MODULE))
        self.manager.add_node(GraphNode(id="B", name="B", node_type=NodeType.MODULE))
        self.manager.add_node(GraphNode(id="C", name="C", node_type=NodeType.MODULE))

        self.assertTrue(self.manager.add_edge(GraphEdge(source_id="A", target_id="B", relation=RelationType.DEPENDS_ON)))
        self.assertTrue(self.manager.add_edge(GraphEdge(source_id="B", target_id="C", relation=RelationType.DEPENDS_ON)))

        # Attempt to add C -> A (cycle)
        edge_added = self.manager.add_edge(GraphEdge(source_id="C", target_id="A", relation=RelationType.DEPENDS_ON))
        self.assertFalse(edge_added)

        # Verify no cycles exist in graph
        cycles = self.manager.detect_cycles()
        self.assertEqual(len(cycles), 0)

    def test_mermaid_diagram_export(self):
        """
        Validates generated Mermaid diagram output with status styling classes.
        """
        self.manager.add_node(GraphNode(id="n_user", name="UserModule", node_type=NodeType.MODULE, status=Status.VERIFIED, confidence_score=95.0))
        self.manager.add_node(GraphNode(id="n_test", name="test_user", node_type=NodeType.TEST, status=Status.VERIFIED, confidence_score=100.0))
        self.manager.add_edge(GraphEdge(source_id="n_test", target_id="n_user", relation=RelationType.VERIFIES))

        mermaid = self.manager.export_mermaid()

        self.assertIn("graph TD", mermaid)
        self.assertIn("UserModule [MODULE]", mermaid)
        self.assertIn("test_user [TEST]", mermaid)
        self.assertIn('n_test -->|"verifies"| n_user', mermaid)
        self.assertIn("classDef verified", mermaid)

    def test_build_from_canonical_state(self):
        """
        Validates automated DAG construction from CanonicalProjectState entities.
        """
        canonical = CanonicalProjectState()
        canonical.conversational_state.user_requirements.append(
            Requirement(id="req_billing", title="Stripe Billing Integration", description="Process payments")
        )
        canonical.project_state.symbols.append(
            AstSymbol(name="BillingService", kind="class", file_path="billing.py", line_start=1, line_end=50)
        )
        canonical.project_state.test_results.append(
            TestResult(
                test_id="t_bill_01",
                name="test_billing_charge",
                suite="test_billing.py",
                status=Status.VERIFIED,
                exit_code=0,
                duration_ms=20.0
            )
        )

        self.manager.build_from_canonical_state(canonical)

        self.assertEqual(len(self.manager.nodes), 3)
        self.assertIn("req_req_billing", self.manager.nodes)
        self.assertIn("sym_BillingService", self.manager.nodes)
        self.assertIn("test_t_bill_01", self.manager.nodes)

        # Test node should verify BillingService symbol
        test_deps = self.manager.get_dependencies("test_t_bill_01")
        self.assertEqual(len(test_deps), 1)
        self.assertEqual(test_deps[0].name, "BillingService")

    def test_invalidation_propagation(self):
        """
        When a dependency changes, downstream dependents should be marked STALE.
        """
        self.manager.add_node(GraphNode(id="core", name="CoreLib", node_type=NodeType.MODULE, status=Status.VERIFIED))
        self.manager.add_node(GraphNode(id="plugin", name="PluginEngine", node_type=NodeType.SERVICE, status=Status.VERIFIED))
        self.manager.add_node(GraphNode(id="ui", name="DashboardUI", node_type=NodeType.COMPONENT, status=Status.VERIFIED))

        self.manager.add_edge(GraphEdge(source_id="ui", target_id="plugin", relation=RelationType.DEPENDS_ON))
        self.manager.add_edge(GraphEdge(source_id="plugin", target_id="core", relation=RelationType.DEPENDS_ON))

        affected = self.manager.propagate_invalidation("core")
        self.assertEqual(set(affected), {"plugin", "ui"})
        self.assertEqual(self.manager.get_node("plugin").status, Status.STALE)
        self.assertEqual(self.manager.get_node("ui").status, Status.STALE)


if __name__ == "__main__":
    unittest.main()
