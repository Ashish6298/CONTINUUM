"""
Project Continuum - Test Suite for Phase 12 (Task-Driven Context Selection)
============================================================================
Milestone 5 - Phase 12.
Validates:
1. Targeted context extraction for a specific task (e.g., "Fix JWT refresh logic").
2. Accurate inclusion of direct dependencies, tests, active constraints, and decisions.
3. Inclusion of relevant failing tests and active contradictions.
4. Omission of unrelated modules to prevent token context bloat.
5. High-density Markdown prompt generation.
"""

import unittest

from core.enums import NodeType, RelationType, Status
from core.state_models import (
    ArchitecturalDecision,
    AstSymbol,
    CanonicalProjectState,
    ContradictionRecord,
    ConversationalState,
    GraphEdge,
    GraphNode,
    ProjectState,
    Requirement,
    TestResult,
)
from context.selector import TaskContextSelector


class TestTaskContextSelector(unittest.TestCase):
    """Test suite for TaskContextSelector."""

    def setUp(self):
        self.selector = TaskContextSelector()

    def test_select_context_for_auth_task(self):
        """
        For a task "Fix JWT refresh token expiry logic", selector must:
        - Select AuthService node & JWT Token API.
        - Include direct DatabasePool dependency.
        - Include JWT architectural decisions and constraints.
        - Omit unrelated Billing and Analytics services.
        """
        canonical = CanonicalProjectState()

        # Graph Nodes
        node_auth = GraphNode(id="node_auth", name="AuthService", node_type=NodeType.SERVICE, status=Status.IN_PROGRESS, confidence_score=70.0)
        node_jwt = GraphNode(id="node_jwt", name="JWTHelper", node_type=NodeType.API, status=Status.VERIFIED, confidence_score=90.0)
        node_db = GraphNode(id="node_db", name="DatabasePool", node_type=NodeType.SERVICE, status=Status.VERIFIED)
        node_billing = GraphNode(id="node_billing", name="BillingService", node_type=NodeType.SERVICE, status=Status.VERIFIED)
        node_analytics = GraphNode(id="node_analytics", name="AnalyticsCollector", node_type=NodeType.SERVICE, status=Status.VERIFIED)

        canonical.graph_nodes = {
            "node_auth": node_auth,
            "node_jwt": node_jwt,
            "node_db": node_db,
            "node_billing": node_billing,
            "node_analytics": node_analytics,
        }

        # Edges
        canonical.graph_edges = [
            GraphEdge(source_id="node_auth", target_id="node_jwt", relation=RelationType.REQUIRES),
            GraphEdge(source_id="node_auth", target_id="node_db", relation=RelationType.DEPENDS_ON),
            GraphEdge(source_id="node_billing", target_id="node_db", relation=RelationType.DEPENDS_ON),
        ]

        # Symbols
        canonical.project_state.symbols = [
            AstSymbol(name="AuthService", kind="class", file_path="auth.py", line_start=1, line_end=60),
            AstSymbol(name="refresh_jwt_token", kind="function", file_path="auth.py", line_start=65, line_end=80),
            AstSymbol(name="BillingGateway", kind="class", file_path="billing.py", line_start=1, line_end=50),
        ]

        # Tests
        canonical.project_state.test_results = [
            TestResult(
                test_id="t_jwt_01",
                name="test_jwt_refresh_expiry",
                suite="test_auth.py",
                status=Status.FAILED,
                exit_code=1,
                duration_ms=15.0,
                error_message="TokenExpiredException not caught"
            ),
            TestResult(
                test_id="t_bill_01",
                name="test_stripe_charge",
                suite="test_billing.py",
                status=Status.VERIFIED,
                exit_code=0,
                duration_ms=25.0
            )
        ]

        # Decisions & Constraints
        canonical.conversational_state.architectural_decisions = [
            ArchitecturalDecision(
                id="dec_01",
                title="JWT Secret and Rotation Policy",
                rationale="Tokens rotate every 15 minutes; refresh tokens valid for 7 days.",
                constraints=["Do not store plain-text secrets in JWT payload", "Enforce RS256 algorithm"]
            ),
            ArchitecturalDecision(
                id="dec_02",
                title="Stripe Webhook Idempotency",
                rationale="Deduplicate webhook event IDs",
                constraints=["Use Redis lock for idempotency"]
            )
        ]

        # Contradictions / Blockers
        canonical.contradictions = [
            ContradictionRecord(
                id="contra_auth",
                severity="HIGH",
                claim_text="Auth refresh verified",
                explanation="test_jwt_refresh_expiry failed with exit code 1",
                resolved=False
            )
        ]

        task_context = self.selector.extract_task_context("Fix JWT refresh token expiry logic", canonical)

        # Verify Primary Nodes
        primary_names = [n.name for n in task_context.primary_nodes]
        self.assertIn("JWTHelper", primary_names)

        # Verify Symbols
        sym_names = [s.name for s in task_context.relevant_symbols]
        self.assertIn("refresh_jwt_token", sym_names)

        # Verify Tests
        test_names = [t.name for t in task_context.relevant_tests]
        self.assertIn("test_jwt_refresh_expiry", test_names)
        self.assertNotIn("test_stripe_charge", test_names)

        # Verify Decisions & Constraints
        self.assertEqual(len(task_context.relevant_decisions), 1)
        self.assertEqual(task_context.relevant_decisions[0].title, "JWT Secret and Rotation Policy")
        self.assertIn("Enforce RS256 algorithm", task_context.active_constraints)

        # Verify Blockers
        self.assertEqual(len(task_context.known_blockers), 1)

        # Verify Unrelated Nodes Omitted
        self.assertGreaterEqual(task_context.omitted_node_count, 2)

        # Verify Markdown briefing formatting
        md = task_context.to_markdown()
        self.assertIn("# Task Briefing: Fix JWT refresh token expiry logic", md)
        self.assertIn("test_jwt_refresh_expiry", md)
        self.assertIn("Enforce RS256 algorithm", md)


if __name__ == "__main__":
    unittest.main()
