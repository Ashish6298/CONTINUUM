"""
Tests for Phase 6: Evidence Resolution Engine
=============================================
Validates:
1. Seniority arbitration: Level 1 test failure overrides Level 5 agent claims of completion.
2. Seniority arbitration: Level 2 AST symbol existence overrides Level 4 outdated docs.
3. Conflict preservation: All competing evidence items are preserved in competing_evidence.
4. Explainability: Rationale strings explain hierarchy levels and winning reasons.
5. Handling targets with only conversational claims (classified as UNVERIFIED).
6. Comprehensive global resolution via resolve_project_state.
"""

import unittest

from core.enums import EvidenceType, EvidenceLevel, Status
from core.evidence import Evidence, EvidenceProvenance
from core.state_models import (
    AgentClaim,
    AstSymbol,
    CanonicalProjectState,
    ProjectState,
    Requirement,
    TestResult,
)
from resolution.resolver import EvidenceResolver


class TestEvidenceResolver(unittest.TestCase):

    def setUp(self):
        self.resolver = EvidenceResolver()

    def test_level_1_test_failure_overrides_level_5_agent_claim(self):
        """
        Crucial test: AI Agent says 'Auth is complete and passing all tests' (Level 5),
        but automated unit test fails with exit code 1 (Level 1).
        Resolution must resolve to FAILED, citing Level 1 test results and preserving the conflict.
        """
        claim_ev = Evidence(
            type=EvidenceType.AGENT_CLAIM,
            level=EvidenceLevel.LEVEL_5_CONVERSATION,
            summary="Agent claimed Auth is complete and passing all tests",
            raw_payload={"claimed_status": "VERIFIED"}
        )

        test_ev = Evidence(
            type=EvidenceType.TEST_RUN,
            level=EvidenceLevel.LEVEL_1_RUNTIME_TEST,
            summary="Test suite 'auth_tests' FAILED with exit code 1",
            raw_payload={"exit_code": 1, "status": "FAILED", "error": "TokenExpiredError"}
        )

        result = self.resolver.resolve_candidates("AuthService", [claim_ev, test_ev])

        self.assertEqual(result.resolved_status, Status.FAILED)
        self.assertEqual(result.winning_evidence.id, test_ev.id)
        self.assertEqual(result.hierarchy_level_used, EvidenceLevel.LEVEL_1_RUNTIME_TEST)
        self.assertTrue(result.conflict_detected)
        self.assertEqual(len(result.competing_evidence), 1)
        self.assertEqual(result.competing_evidence[0].id, claim_ev.id)
        self.assertIn("Level 1", result.rationale)
        self.assertIn("Overrode conflicting lower-tier", result.rationale)

    def test_level_2_ast_overrides_level_4_documentation(self):
        """
        Level 2 AST symbol existence overrides Level 4 outdated README saying feature is planned.
        """
        doc_ev = Evidence(
            type=EvidenceType.DOCUMENTATION,
            level=EvidenceLevel.LEVEL_4_DOCUMENTATION,
            summary="README.md mentions PaymentService as planned",
            raw_payload={"status": "PLANNED"}
        )

        ast_ev = Evidence(
            type=EvidenceType.AST_SYMBOL,
            level=EvidenceLevel.LEVEL_2_CODE_AST,
            summary="Extracted class PaymentService in src/payment.py",
            raw_payload={"symbols": [{"name": "PaymentService", "kind": "class"}], "file_path": "src/payment.py"}
        )

        result = self.resolver.resolve_candidates("PaymentService", [doc_ev, ast_ev])

        self.assertEqual(result.resolved_status, Status.PARTIAL)
        self.assertEqual(result.winning_evidence.id, ast_ev.id)
        self.assertEqual(result.hierarchy_level_used, EvidenceLevel.LEVEL_2_CODE_AST)
        self.assertTrue(result.conflict_detected)

    def test_only_conversational_claim_resolves_to_unverified(self):
        """
        When a component has only agent claims with no physical evidence,
        status must resolve strictly to UNVERIFIED.
        """
        claims = [{"claimed_status": "VERIFIED", "claim_text": "I finished Stripe checkout"}]
        result = self.resolver.resolve_candidates("StripeCheckout", [], claims=claims)

        self.assertEqual(result.resolved_status, Status.UNVERIFIED)
        self.assertIsNone(result.winning_evidence)
        self.assertIn("UNVERIFIED", result.rationale)

    def test_global_resolve_project_state(self):
        state = CanonicalProjectState(project_id="resolve_test_proj")

        # 1. Add Requirement
        req = Requirement(id="req_jwt", title="JWT Authentication", description="Implement JWT", status=Status.PENDING)
        state.conversational_state.user_requirements.append(req)

        # 2. Add Test Evidence for JWT
        test_ev = Evidence(
            type=EvidenceType.TEST_RUN,
            level=EvidenceLevel.LEVEL_1_RUNTIME_TEST,
            summary="JWT Authentication test suite passed",
            raw_payload={"exit_code": 0, "status": "VERIFIED"}
        )
        state.add_evidence(test_ev)
        req.evidence_id = test_ev.id

        # 3. Add AST Symbol
        sym = AstSymbol(name="JwtManager", kind="class", file_path="src/jwt.py", line_start=1, line_end=20, exported=True)
        state.project_state.symbols.append(sym)
        sym_ev = Evidence(
            type=EvidenceType.AST_SYMBOL,
            level=EvidenceLevel.LEVEL_2_CODE_AST,
            summary="Extracted class JwtManager in src/jwt.py",
            raw_payload={"symbols": [{"name": "JwtManager"}]}
        )
        state.add_evidence(sym_ev)
        sym.evidence_id = sym_ev.id

        # Run global resolution
        results = self.resolver.resolve_project_state(state)

        self.assertIn("req_jwt", results)
        self.assertEqual(results["req_jwt"].resolved_status, Status.VERIFIED)
        self.assertEqual(req.status, Status.VERIFIED)

        self.assertIn("JwtManager", results)
        self.assertEqual(results["JwtManager"].resolved_status, Status.PARTIAL)


if __name__ == "__main__":
    unittest.main()
