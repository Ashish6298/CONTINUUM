"""
Project Continuum - Test Suite for Phase 8 (Confidence Calculation Engine)
==========================================================================
Milestone 3 - Phase 8.
Validates multi-dimensional confidence calculation, contradiction caps, and
global project state confidence evaluation.
"""

import unittest

from core.enums import EvidenceLevel, EvidenceType, NodeType, Status
from core.evidence import Evidence, EvidenceProvenance
from core.state_models import (
    AgentClaim,
    AstSymbol,
    CanonicalProjectState,
    ContradictionRecord,
    ConversationalState,
    GitState,
    GraphNode,
    ProjectState,
    Requirement,
    TestResult,
)
from confidence.calculator import ConfidenceCalculator
from confidence.models import ConfidenceBreakdown


class TestConfidenceCalculator(unittest.TestCase):
    """Test suite for ConfidenceCalculator."""

    def setUp(self):
        self.calculator = ConfidenceCalculator()

    def test_full_verified_stack_high_confidence(self):
        """
        Component with code implementation, passing tests, clean git, and docs
        should score between 90.0% and 100.0%.
        """
        ev_code = Evidence(
            id="ev_code_01",
            type=EvidenceType.AST_SYMBOL,
            level=EvidenceLevel.LEVEL_2_CODE_AST,
            summary="AuthService class defined with 4 methods",
            raw_payload={"symbols": [{"name": "AuthService"}], "errors": []},
            provenance=EvidenceProvenance(extractor_name="python_parser", source_uri="auth.py", locator="class:AuthService")
        )

        ev_test = Evidence(
            id="ev_test_01",
            type=EvidenceType.TEST_RUN,
            level=EvidenceLevel.LEVEL_1_RUNTIME_TEST,
            summary="auth test suite passed",
            raw_payload={"exit_code": 0, "passed": 5, "failed": 0},
            provenance=EvidenceProvenance(extractor_name="pytest", source_uri="test_auth.py", locator="exit_code:0")
        )

        ev_git = Evidence(
            id="ev_git_01",
            type=EvidenceType.GIT_STATUS,
            level=EvidenceLevel.LEVEL_3_GIT_STATE,
            summary="Clean working tree",
            raw_payload={"is_dirty": False},
            provenance=EvidenceProvenance(extractor_name="git_extractor", source_uri=".git", locator="status")
        )

        ev_doc = Evidence(
            id="ev_doc_01",
            type=EvidenceType.DOCUMENTATION,
            level=EvidenceLevel.LEVEL_4_DOCUMENTATION,
            summary="Authentication Architecture Documentation",
            raw_payload={"content": "Auth service handles JWT validation."},
            provenance=EvidenceProvenance(extractor_name="workspace_extractor", source_uri="docs/auth.md", locator="markdown")
        )

        node = GraphNode(
            id="node_auth",
            name="AuthService",
            node_type=NodeType.COMPONENT,
            status=Status.VERIFIED,
            evidence_ids=["ev_code_01", "ev_test_01", "ev_git_01", "ev_doc_01"]
        )

        evidence_pool = {
            "ev_code_01": ev_code,
            "ev_test_01": ev_test,
            "ev_git_01": ev_git,
            "ev_doc_01": ev_doc
        }

        score, breakdown_dict = self.calculator.calculate_node_confidence(node, evidence_pool, [])

        self.assertGreaterEqual(score, 90.0)
        self.assertEqual(score, 100.0)
        self.assertEqual(node.confidence_score, 100.0)
        self.assertEqual(breakdown_dict["implementation_presence"], 35.0)
        self.assertEqual(breakdown_dict["test_existence"], 15.0)
        self.assertEqual(breakdown_dict["test_execution_pass"], 30.0)
        self.assertEqual(breakdown_dict["git_consistency"], 10.0)
        self.assertEqual(breakdown_dict["documentation_presence"], 10.0)

    def test_code_only_without_tests_moderate_confidence(self):
        """
        Component with source code implementation and clean git, but no tests or docs
        should score approximately 45.0% (35 code + 10 git).
        """
        ev_code = Evidence(
            id="ev_code_02",
            type=EvidenceType.AST_SYMBOL,
            level=EvidenceLevel.LEVEL_2_CODE_AST,
            summary="MetricsCollector class defined",
            raw_payload={"symbols": [{"name": "MetricsCollector"}]},
            provenance=EvidenceProvenance(extractor_name="python_parser", source_uri="metrics.py", locator="class:MetricsCollector")
        )

        ev_git = Evidence(
            id="ev_git_02",
            type=EvidenceType.GIT_STATUS,
            level=EvidenceLevel.LEVEL_3_GIT_STATE,
            summary="Clean working tree",
            raw_payload={"is_dirty": False},
            provenance=EvidenceProvenance(extractor_name="git_extractor", source_uri=".git", locator="status")
        )

        node = GraphNode(
            id="node_metrics",
            name="MetricsCollector",
            node_type=NodeType.COMPONENT,
            evidence_ids=["ev_code_02", "ev_git_02"]
        )

        evidence_pool = {"ev_code_02": ev_code, "ev_git_02": ev_git}
        score, breakdown = self.calculator.calculate_node_confidence(node, evidence_pool, [])

        self.assertEqual(score, 45.0)
        self.assertEqual(breakdown["test_existence"], 0.0)
        self.assertEqual(breakdown["test_execution_pass"], 0.0)

    def test_unbacked_conversational_claim_capped_at_fifteen_percent(self):
        """
        A component backed ONLY by a chat claim (Level 5) with zero physical evidence
        must be hard-capped at max 15.0%.
        """
        ev_claim = Evidence(
            id="ev_claim_01",
            type=EvidenceType.AGENT_CLAIM,
            level=EvidenceLevel.LEVEL_5_CONVERSATION,
            summary="Agent claim: Payment is 100% complete",
            raw_payload={"claimed_status": "VERIFIED"},
            provenance=EvidenceProvenance(extractor_name="conversation_extractor", source_uri="chat.json", locator="turn:5")
        )

        node = GraphNode(
            id="node_payment",
            name="PaymentService",
            node_type=NodeType.COMPONENT,
            evidence_ids=["ev_claim_01"]
        )

        evidence_pool = {"ev_claim_01": ev_claim}
        score, breakdown = self.calculator.calculate_node_confidence(node, evidence_pool, [])

        self.assertLessEqual(score, 15.0)
        self.assertIn("Unbacked conversational claim", breakdown["explanation"])

    def test_high_severity_contradiction_hard_cap(self):
        """
        Even if physical code exists, if there is an active HIGH severity contradiction
        (e.g. failing tests, false claim), confidence must be capped at max 20.0%.
        """
        ev_code = Evidence(
            id="ev_code_03",
            type=EvidenceType.AST_SYMBOL,
            level=EvidenceLevel.LEVEL_2_CODE_AST,
            summary="BillingService class defined",
            raw_payload={"symbols": [{"name": "BillingService"}]},
            provenance=EvidenceProvenance(extractor_name="python_parser", source_uri="billing.py", locator="class:BillingService")
        )

        ev_test_fail = Evidence(
            id="ev_test_fail_03",
            type=EvidenceType.TEST_RUN,
            level=EvidenceLevel.LEVEL_1_RUNTIME_TEST,
            summary="Billing tests failed",
            raw_payload={"exit_code": 1},
            provenance=EvidenceProvenance(extractor_name="pytest", source_uri="test_billing.py", locator="exit_code:1")
        )

        node = GraphNode(
            id="node_billing",
            name="BillingService",
            node_type=NodeType.COMPONENT,
            evidence_ids=["ev_code_03", "ev_test_fail_03"]
        )

        contradiction = ContradictionRecord(
            id="contra_01",
            severity="HIGH",
            claim_id="node_billing",
            claim_text="Billing is done",
            explanation="Billing test failed with exit code 1",
            resolved=False
        )

        evidence_pool = {"ev_code_03": ev_code, "ev_test_fail_03": ev_test_fail}
        score, breakdown = self.calculator.calculate_node_confidence(node, evidence_pool, [contradiction])

        self.assertLessEqual(score, 20.0)
        self.assertEqual(breakdown["contradiction_cap"], 20.0)
        self.assertIn("Capped at 20% due to active contradictions", breakdown["explanation"])

    def test_global_project_confidence_synthesis(self):
        """
        Validates global project confidence calculation across registered nodes,
        requirements, physical test rate, and contradiction impact.
        """
        canonical = CanonicalProjectState()
        canonical.project_state.files = ["app.py", "auth.py", "test_auth.py"]
        canonical.project_state.symbols = [
            AstSymbol(name="AuthService", kind="class", file_path="auth.py", line_start=1, line_end=40)
        ]
        canonical.project_state.test_results = [
            TestResult(
                test_id="t1",
                name="test_login",
                suite="test_auth.py",
                status=Status.VERIFIED,
                exit_code=0,
                duration_ms=10.0
            )
        ]
        canonical.project_state.git_state = GitState(is_repo=True, is_dirty=False)

        score, summary = self.calculator.calculate_project_confidence(canonical)

        self.assertGreaterEqual(score, 70.0)
        self.assertEqual(summary["test_pass_rate"], 100.0)
        self.assertTrue(summary["has_physical_code"])
        self.assertEqual(summary["unresolved_contradictions"], 0)


if __name__ == "__main__":
    unittest.main()
