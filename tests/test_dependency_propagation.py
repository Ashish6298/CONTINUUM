"""
Project Continuum - Test Suite for Phase 10 (Dependency Invalidation & Status Propagation)
===========================================================================================
Milestone 4 - Phase 10.
Validates:
1. Schema modification propagates STALE to downstream dependents (without falsely marking FAILED).
2. Upstream failure propagates BLOCKED to critical downstream dependents.
3. Accurate identification of unresolved dependencies.
4. Discovery of next actionable unblocked work.
5. Synthesis of NextActionRecommendation.
"""

import unittest

from core.enums import NodeType, RelationType, Status
from core.state_models import GraphEdge, GraphNode
from graph.manager import StateGraphManager
from graph.propagator import DependencyPropagator


class TestDependencyPropagation(unittest.TestCase):
    """Test suite for DependencyPropagator & Phase 10 Invalidation workflows."""

    def setUp(self):
        self.manager = StateGraphManager()
        self.propagator = DependencyPropagator(self.manager)

    def test_schema_change_marks_dependents_stale_not_failed(self):
        """
        Database schema changes (marked STALE) -> Dependent API and UI become STALE,
        never falsely marked FAILED.
        """
        db = GraphNode(id="db_schema", name="UserDBSchema", node_type=NodeType.COMPONENT, status=Status.VERIFIED)
        api = GraphNode(id="user_api", name="UserRestAPI", node_type=NodeType.API, status=Status.VERIFIED)
        ui = GraphNode(id="user_ui", name="UserProfileUI", node_type=NodeType.COMPONENT, status=Status.VERIFIED)

        self.manager.add_node(db)
        self.manager.add_node(api)
        self.manager.add_node(ui)

        self.manager.add_edge(GraphEdge(source_id="user_api", target_id="db_schema", relation=RelationType.DEPENDS_ON))
        self.manager.add_edge(GraphEdge(source_id="user_ui", target_id="user_api", relation=RelationType.DEPENDS_ON))

        # Propagate schema modification
        result = self.propagator.propagate_change("db_schema", new_status=Status.STALE)

        self.assertEqual(len(result.affected_node_ids), 2)
        self.assertIn("user_api", result.stale_node_ids)
        self.assertIn("user_ui", result.stale_node_ids)
        self.assertEqual(self.manager.get_node("user_api").status, Status.STALE)
        self.assertEqual(self.manager.get_node("user_ui").status, Status.STALE)
        self.assertEqual(len(result.blocked_node_ids), 0)

    def test_upstream_failure_blocks_critical_downstream(self):
        """
        AuthService fails test execution (Status.FAILED) ->
        Dependent PaymentGateway and OrderService become Status.BLOCKED.
        """
        auth = GraphNode(id="auth_svc", name="AuthService", node_type=NodeType.SERVICE, status=Status.VERIFIED)
        payment = GraphNode(id="payment_svc", name="PaymentService", node_type=NodeType.SERVICE, status=Status.VERIFIED)
        order = GraphNode(id="order_svc", name="OrderService", node_type=NodeType.SERVICE, status=Status.VERIFIED)

        self.manager.add_node(auth)
        self.manager.add_node(payment)
        self.manager.add_node(order)

        self.manager.add_edge(GraphEdge(source_id="payment_svc", target_id="auth_svc", relation=RelationType.DEPENDS_ON))
        self.manager.add_edge(GraphEdge(source_id="order_svc", target_id="payment_svc", relation=RelationType.DEPENDS_ON))

        # Fail auth service
        result = self.propagator.propagate_change("auth_svc", new_status=Status.FAILED)

        self.assertEqual(self.manager.get_node("auth_svc").status, Status.FAILED)
        self.assertEqual(self.manager.get_node("payment_svc").status, Status.BLOCKED)
        self.assertIn("payment_svc", result.blocked_node_ids)

    def test_unresolved_dependency_identification(self):
        """
        Node requires 3 dependencies: 1 VERIFIED, 1 PENDING, 1 STALE.
        get_unresolved_dependencies must return exactly the 2 unverified ones.
        """
        target = GraphNode(id="target_node", name="TargetApp", node_type=NodeType.COMPONENT, status=Status.PENDING)
        dep_good = GraphNode(id="dep_good", name="Config", node_type=NodeType.MODULE, status=Status.VERIFIED)
        dep_pending = GraphNode(id="dep_pending", name="Auth", node_type=NodeType.SERVICE, status=Status.PENDING)
        dep_stale = GraphNode(id="dep_stale", name="Database", node_type=NodeType.SERVICE, status=Status.STALE)

        self.manager.add_node(target)
        self.manager.add_node(dep_good)
        self.manager.add_node(dep_pending)
        self.manager.add_node(dep_stale)

        self.manager.add_edge(GraphEdge(source_id="target_node", target_id="dep_good", relation=RelationType.DEPENDS_ON))
        self.manager.add_edge(GraphEdge(source_id="target_node", target_id="dep_pending", relation=RelationType.DEPENDS_ON))
        self.manager.add_edge(GraphEdge(source_id="target_node", target_id="dep_stale", relation=RelationType.DEPENDS_ON))

        unresolved = self.propagator.get_unresolved_dependencies("target_node")
        unresolved_ids = [u.id for u in unresolved]

        self.assertEqual(len(unresolved), 2)
        self.assertIn("dep_pending", unresolved_ids)
        self.assertIn("dep_stale", unresolved_ids)
        self.assertNotIn("dep_good", unresolved_ids)

    def test_determine_next_actionable_nodes(self):
        """
        Graph has:
        - Task 1: No dependencies, Status.PENDING -> ACTIONABLE
        - Task 2: Depends on Task 1 (not verified yet) -> NOT actionable
        - Task 3: Depends on Module A (Status.VERIFIED), Status.STALE -> ACTIONABLE
        """
        t1 = GraphNode(id="task_1", name="Setup Logging", node_type=NodeType.TASK, status=Status.PENDING)
        t2 = GraphNode(id="task_2", name="Add Log Stream", node_type=NodeType.TASK, status=Status.PENDING)
        mod_a = GraphNode(id="mod_a", name="CoreLib", node_type=NodeType.MODULE, status=Status.VERIFIED)
        t3 = GraphNode(id="task_3", name="Implement Controller", node_type=NodeType.TASK, status=Status.STALE)

        self.manager.add_node(t1)
        self.manager.add_node(t2)
        self.manager.add_node(mod_a)
        self.manager.add_node(t3)

        self.manager.add_edge(GraphEdge(source_id="task_2", target_id="task_1", relation=RelationType.DEPENDS_ON))
        self.manager.add_edge(GraphEdge(source_id="task_3", target_id="mod_a", relation=RelationType.DEPENDS_ON))

        actionable = self.propagator.determine_next_actionable_nodes()
        actionable_ids = [a.id for a in actionable]

        self.assertIn("task_1", actionable_ids)
        self.assertIn("task_3", actionable_ids)
        self.assertNotIn("task_2", actionable_ids)

    def test_recommend_next_action(self):
        """
        Recommends concrete next action based on active graph topology.
        """
        test_node = GraphNode(id="test_suite_01", name="test_security", node_type=NodeType.TEST, status=Status.PENDING)
        self.manager.add_node(test_node)

        rec = self.propagator.recommend_next_action()
        self.assertIsNotNone(rec)
        self.assertEqual(rec.action_type, "RUN_TEST")
        self.assertEqual(rec.target_uri, "test_suite_01")
        self.assertIn("test_security", rec.description)


if __name__ == "__main__":
    unittest.main()
