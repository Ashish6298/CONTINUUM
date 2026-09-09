"""
Tests verifying strict ontological separation between:
1. Project State (Physical Reality)
2. Conversational State (Intent & Reasoning Claims)
3. Agent Execution State (Tactical In-Flight Intent)
"""

import unittest
from core.enums import Status, EvidenceType
from core.evidence import Evidence, EvidenceProvenance
from core.state_models import (
    CanonicalProjectState,
    ProjectState,
    ConversationalState,
    AgentExecutionState,
    AstSymbol,
    TestResult,
    GitState,
    Requirement,
    AgentClaim,
    TacticalTask,
    NextActionRecommendation,
    ContradictionRecord
)


class TestStateIsolation(unittest.TestCase):

    def setUp(self):
        self.canonical = CanonicalProjectState(
            project_id="proj_continuum_test",
            project_state=ProjectState(
                root_path="d:/CONTINUUM",
                detected_languages=["python", "markdown"],
                files=["d:/CONTINUUM/pyproject.toml", "d:/CONTINUUM/continuum/core/enums.py"]
            ),
            conversational_state=ConversationalState(
                session_id="sess_12345"
            ),
            agent_execution_state=AgentExecutionState(
                agent_id="agent_alpha",
                model_name="claude-3-5-sonnet"
            )
        )

    def test_three_states_are_independent_objects(self):
        ps = self.canonical.project_state
        cs = self.canonical.conversational_state
        aes = self.canonical.agent_execution_state

        self.assertIsInstance(ps, ProjectState)
        self.assertIsInstance(cs, ConversationalState)
        self.assertIsInstance(aes, AgentExecutionState)

        # Ensure no cross-references or shared object mutation
        self.assertIsNot(ps, cs)
        self.assertIsNot(cs, aes)
        self.assertIsNot(ps, aes)

    def test_agent_claim_does_not_mutate_physical_project_state(self):
        """
        Crucial principle: When an AI agent claims in chat that 'Payment service is complete',
        it MUST ONLY enter conversational_state.agent_claims and NEVER prematurely mark
        any physical test_results or symbols as existing in project_state.
        """
        claim_ev = Evidence(
            type=EvidenceType.AGENT_CLAIM,
            summary="Agent claimed payment service is finished",
            raw_payload={"message": "I finished the Stripe payment integration."}
        )
        self.canonical.add_evidence(claim_ev)

        # Record conversational claim
        claim = AgentClaim(
            id="claim_001",
            claim_text="I finished the Stripe payment integration.",
            target_component="PaymentService",
            claimed_status=Status.VERIFIED,
            source_agent="agent_alpha",
            evidence_id=claim_ev.id
        )
        self.canonical.conversational_state.agent_claims.append(claim)

        # Physical project state must remain unchanged and unpolluted
        self.assertEqual(len(self.canonical.project_state.symbols), 0)
        self.assertEqual(len(self.canonical.project_state.test_results), 0)
        self.assertEqual(self.canonical.project_state.build_status, Status.UNKNOWN)

    def test_contradiction_generation_preserves_both_truths(self):
        """
        When physical reality contradicts conversational claims, both records are
        preserved with a ContradictionRecord connecting them.
        """
        # Conversational claim
        claim = AgentClaim(
            id="claim_jwt",
            claim_text="JWT verification is 100% complete and passing tests.",
            target_component="JwtService",
            claimed_status=Status.VERIFIED
        )
        self.canonical.conversational_state.agent_claims.append(claim)

        # Physical test result (failing exit code 1)
        failing_test = TestResult(
            test_id="test_jwt_01",
            name="test_verify_signature",
            suite="auth_suite",
            status=Status.FAILED,
            exit_code=1,
            duration_ms=120.0,
            error_message="SignatureVerificationError: Invalid key"
        )
        self.canonical.project_state.test_results.append(failing_test)

        # Record explicit contradiction
        contradiction = ContradictionRecord(
            id="contra_jwt_01",
            severity="HIGH",
            claim_id=claim.id,
            claim_text=claim.claim_text,
            physical_evidence_id=failing_test.test_id,
            explanation="Agent claimed JWT tests are passing, but test_verify_signature exited with code 1 (FAILED)."
        )
        self.canonical.contradictions.append(contradiction)

        self.assertEqual(len(self.canonical.contradictions), 1)
        self.assertEqual(self.canonical.contradictions[0].severity, "HIGH")
        # Physical state still records failure truthfully
        self.assertEqual(self.canonical.project_state.test_results[0].status, Status.FAILED)
        # Conversational state still records the agent's claim truthfully for auditing
        self.assertEqual(self.canonical.conversational_state.agent_claims[0].claimed_status, Status.VERIFIED)

    def test_agent_execution_state_isolation(self):
        """
        Tactical in-flight actions (e.g. pending edits, next action) do not contaminate
        either conversational requirements or physical files list.
        """
        task = TacticalTask(
            id="task_refactor_db",
            title="Refactoring database connection pool",
            status=Status.IN_PROGRESS,
            target_files=["d:/CONTINUUM/src/db/pool.py"]
        )
        self.canonical.agent_execution_state.active_tasks.append(task)
        self.canonical.agent_execution_state.modified_files_in_flight.append("d:/CONTINUUM/src/db/pool.py")
        self.canonical.agent_execution_state.next_action = NextActionRecommendation(
            action_type="RUN_TEST",
            target_uri="tests/test_pool.py",
            description="Run database connection pool test after refactoring"
        )

        # Confirm isolation
        self.assertEqual(len(self.canonical.conversational_state.user_requirements), 0)
        self.assertNotIn("d:/CONTINUUM/src/db/pool.py", self.canonical.project_state.files)


if __name__ == "__main__":
    unittest.main()
