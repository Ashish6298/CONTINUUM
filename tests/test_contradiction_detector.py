"""
Project Continuum - Test Suite for Phase 7 (Contradiction Detection Engine)
===========================================================================
Milestone 3 - Phase 7.
Validates detection of:
1. False completion claims with missing AST/physical code.
2. Passing claims when automated test results failed.
3. Documentation referencing missing symbols.
4. Clean working tree claims against dirty Git state.
5. Clean project with zero contradictions.
6. Discrepancy ledger operations and resolution status.
"""

import unittest
from datetime import datetime, timezone

from core.enums import EvidenceLevel, EvidenceType, Status
from core.evidence import Evidence, EvidenceProvenance
from core.state_models import (
    AgentClaim,
    AstSymbol,
    CanonicalProjectState,
    ConversationalState,
    GitState,
    ProjectState,
    TestResult,
)
from contradictions.detector import ContradictionDetector
from contradictions.models import ContradictionSeverity, DiscrepancyLedger


class TestContradictionDetector(unittest.TestCase):
    """Test suite for ContradictionDetector."""

    def setUp(self):
        self.detector = ContradictionDetector()

    def test_detect_claim_vs_missing_implementation(self):
        """
        AI agent claims in chat: 'Authentication service is completely implemented and ready',
        but there are no auth symbols or files in the workspace.
        Continuum must flag this as a HIGH severity contradiction.
        """
        project_state = ProjectState(
            root_path="D:/mock_project",
            files=["utils.py", "models.py"],
            symbols=[
                AstSymbol(name="format_date", kind="function", file_path="utils.py", line_start=1, line_end=5),
                AstSymbol(name="User", kind="class", file_path="models.py", line_start=1, line_end=20)
            ]
        )

        conversational_state = ConversationalState(
            agent_claims=[
                AgentClaim(
                    id="claim_auth_done",
                    claim_text="Authentication service is completely implemented and ready",
                    target_component="AuthService",
                    claimed_status=Status.VERIFIED
                )
            ]
        )

        evidence_pool = {}
        contradictions = self.detector.detect_contradictions(project_state, conversational_state, evidence_pool)

        self.assertEqual(len(contradictions), 1)
        contra = contradictions[0]
        self.assertEqual(contra.severity, ContradictionSeverity.HIGH.value)
        self.assertEqual(contra.claim_id, "claim_auth_done")
        self.assertIn("AuthService", contra.explanation)
        self.assertIn("no matching AST symbols", contra.explanation)
        self.assertFalse(contra.resolved)

    def test_detect_claim_vs_failing_tests(self):
        """
        AI agent claims 'All payment tests are passing with 100% success',
        but recorded test execution indicates test_charge_card FAILED (exit code 1).
        """
        failing_test = TestResult(
            test_id="test_pay_01",
            name="test_charge_card",
            suite="test_payment.py",
            status=Status.FAILED,
            exit_code=1,
            duration_ms=45.0,
            error_message="AssertionError: 400 != 200",
            evidence_id="ev_test_fail"
        )

        test_ev = Evidence(
            id="ev_test_fail",
            type=EvidenceType.TEST_RUN,
            level=EvidenceLevel.LEVEL_1_RUNTIME_TEST,
            summary="Payment test suite failed",
            raw_payload={"exit_code": 1, "failed": 1, "passed": 0},
            provenance=EvidenceProvenance(extractor_name="pytest", source_uri="test_payment.py", locator="exit_code:1")
        )

        project_state = ProjectState(
            root_path="D:/mock_project",
            test_results=[failing_test]
        )

        conversational_state = ConversationalState(
            agent_claims=[
                AgentClaim(
                    id="claim_pay_green",
                    claim_text="Payment processing is verified and all payment tests pass",
                    target_component="payment",
                    claimed_status=Status.VERIFIED
                )
            ]
        )

        evidence_pool = {"ev_test_fail": test_ev}
        contradictions = self.detector.detect_contradictions(project_state, conversational_state, evidence_pool)

        self.assertEqual(len(contradictions), 1)
        contra = contradictions[0]
        self.assertEqual(contra.severity, ContradictionSeverity.HIGH.value)
        self.assertEqual(contra.claim_id, "claim_pay_green")
        self.assertEqual(contra.physical_evidence_id, "ev_test_fail")
        self.assertIn("failed with exit code 1", contra.explanation)

    def test_detect_doc_vs_missing_symbols(self):
        """
        Documentation in README.md describes `StripeWebhookProcessor` and `StripeApiClient`,
        neither of which exists in the extracted AST symbols.
        """
        doc_ev = Evidence(
            id="ev_readme",
            type=EvidenceType.DOCUMENTATION,
            level=EvidenceLevel.LEVEL_4_DOCUMENTATION,
            summary="API Documentation",
            raw_payload={
                "content": "# Billing\nTo process webhooks use `StripeWebhookProcessor` and invoke `StripeApiClient`."
            },
            provenance=EvidenceProvenance(extractor_name="workspace_extractor", source_uri="README.md", locator="markdown")
        )

        project_state = ProjectState(
            root_path="D:/mock_project",
            symbols=[
                AstSymbol(name="SimpleLogger", kind="class", file_path="logger.py", line_start=1, line_end=10)
            ]
        )

        conversational_state = ConversationalState()
        evidence_pool = {"ev_readme": doc_ev}

        contradictions = self.detector.detect_contradictions(project_state, conversational_state, evidence_pool)

        self.assertEqual(len(contradictions), 1)
        contra = contradictions[0]
        self.assertEqual(contra.severity, ContradictionSeverity.MEDIUM.value)
        self.assertEqual(contra.physical_evidence_id, "ev_readme")
        self.assertIn("StripeWebhookProcessor", contra.explanation)

    def test_detect_stale_git_dirty_claim(self):
        """
        Agent claims 'Everything is committed and clean', but Git state is dirty.
        """
        git_ev = Evidence(
            id="ev_git_dirty",
            type=EvidenceType.GIT_STATUS,
            level=EvidenceLevel.LEVEL_3_GIT_STATE,
            summary="Git status: dirty",
            raw_payload={"is_dirty": True},
            provenance=EvidenceProvenance(extractor_name="git_extractor", source_uri=".git", locator="status")
        )

        project_state = ProjectState(
            root_path="D:/mock_project",
            git_state=GitState(
                is_repo=True,
                is_dirty=True,
                unstaged_files=["app.py"],
                untracked_files=["temp.log"],
                evidence_ids=["ev_git_dirty"]
            )
        )

        conversational_state = ConversationalState(
            agent_claims=[
                AgentClaim(
                    id="claim_clean",
                    claim_text="All changes committed, clean working tree ready for handoff",
                    claimed_status=Status.VERIFIED
                )
            ]
        )

        evidence_pool = {"ev_git_dirty": git_ev}
        contradictions = self.detector.detect_contradictions(project_state, conversational_state, evidence_pool)

        self.assertEqual(len(contradictions), 1)
        contra = contradictions[0]
        self.assertEqual(contra.severity, ContradictionSeverity.MEDIUM.value)
        self.assertEqual(contra.claim_id, "claim_clean")
        self.assertIn("DIRTY", contra.explanation)

    def test_clean_project_state_zero_contradictions(self):
        """
        Legitimate project where claims accurately match AST symbols, tests pass,
        and Git is clean. Should produce 0 contradictions.
        """
        project_state = ProjectState(
            root_path="D:/valid_project",
            files=["auth_service.py"],
            symbols=[
                AstSymbol(name="AuthService", kind="class", file_path="auth_service.py", line_start=1, line_end=50)
            ],
            test_results=[
                TestResult(
                    test_id="t1",
                    name="test_login",
                    suite="test_auth.py",
                    status=Status.VERIFIED,
                    exit_code=0,
                    duration_ms=12.0
                )
            ],
            git_state=GitState(is_repo=True, is_dirty=False)
        )

        conversational_state = ConversationalState(
            agent_claims=[
                AgentClaim(
                    id="c1",
                    claim_text="AuthService is implemented",
                    target_component="AuthService",
                    claimed_status=Status.VERIFIED
                )
            ]
        )

        contradictions = self.detector.detect_contradictions(project_state, conversational_state, {})
        self.assertEqual(len(contradictions), 0)

    def test_discrepancy_ledger_audit_and_resolution(self):
        """
        Verifies that audit_canonical_state properly populates the DiscrepancyLedger,
        filters by severity, and allows marking discrepancies as resolved.
        """
        canonical = CanonicalProjectState()
        canonical.conversational_state.agent_claims.append(
            AgentClaim(
                id="claim_db",
                claim_text="DatabaseMigrationManager finished",
                target_component="DatabaseMigrationManager",
                claimed_status=Status.VERIFIED
            )
        )

        ledger = self.detector.audit_canonical_state(canonical)
        self.assertEqual(len(ledger.records), 1)
        self.assertEqual(len(ledger.get_unresolved()), 1)
        self.assertEqual(len(ledger.get_by_severity("HIGH")), 1)

        # Mark as resolved
        record_id = ledger.records[0].id
        resolved_ok = ledger.resolve_record(record_id)
        self.assertTrue(resolved_ok)
        self.assertEqual(len(ledger.get_unresolved()), 0)

        # Check serialization
        d = ledger.to_dict()
        self.assertEqual(d["unresolved_count"], 0)
        self.assertEqual(d["high_severity_count"], 1)


if __name__ == "__main__":
    unittest.main()
