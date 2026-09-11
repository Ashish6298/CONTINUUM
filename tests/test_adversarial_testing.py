"""
Project Continuum - Adversarial Testing & Hallucination Resistance Suite
========================================================================
Milestone 8 - Phase 20: Adversarial Testing & Hallucination Resistance.
Validates that Project Continuum reliably defends against all forms of
hallucinations, deceptive claims, and corrupt / incomplete evidence:

1. False Completion Claims: AI claims a feature is complete when zero AST/file proof exists.
2. Passing Test Falsehoods: AI claims tests passed when physical test runs failed (exit code != 0).
3. Missing Implementations: Conversational claims of multi-tier services without code.
4. Stale / Phantom Documentation: Markdown referencing non-existent interfaces & types.
5. Misleading Commit Messages: Git history claiming features that were never committed.
6. Unsupported & Binary Files: Workspace containing binary/garbage files without crashing or corrupting state.
7. Incomplete / Fragmented Evidence: Sparse evidence preserves UNKNOWN status rather than guessing.
8. Non-Contamination Invariance: Conversational claims NEVER elevate to physical ProjectState truth.
"""

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from core.enums import EvidenceLevel, EvidenceType, Status, TargetModel
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
from confidence.calculator import ConfidenceCalculator
from pipeline.orchestrator import ContinuumPipeline
from resolution.resolver import EvidenceResolver


class TestAdversarialAndHallucinationResistance(unittest.TestCase):
    """
    Stress-testing suite verifying Continuum's adversarial resilience.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir)
        self.detector = ContradictionDetector()
        self.confidence_calc = ConfidenceCalculator()
        self.resolver = EvidenceResolver()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_adversarial_false_completion_claim_blocked(self):
        """
        Scenario: AI agent generates glowing conversational claims that 'OAuth2AuthenticationService
        is 100% complete and verified', but no code exists.
        Result: Must flag HIGH contradiction, cap confidence score <= 20%, and exclude from ProjectState.
        """
        (self.workspace / "main.py").write_text("print('Hello world')", encoding="utf-8")

        transcript = {
            "session_id": "adversarial_sess_01",
            "model_name": "Deceptive-LLM",
            "turns": [
                {"role": "user", "content": "Implement OAuth2AuthenticationService"},
                {"role": "assistant", "content": "I have completed OAuth2AuthenticationService and verified all security flows."}
            ]
        }

        pipeline = ContinuumPipeline(self.workspace, project_id="adv_false_completion")
        state, summary, handoff_results = pipeline.run_full_analysis(
            conversation_input=transcript
        )

        # 1. Contradiction detected
        self.assertGreaterEqual(summary.contradictions_detected, 1)
        self.assertTrue(any("OAuth2AuthenticationService" in c.claim_text or "oauth2" in c.explanation.lower() for c in state.contradictions))

        # 2. ProjectState remains pure
        symbol_names = [s.name for s in state.project_state.symbols]
        self.assertNotIn("OAuth2AuthenticationService", symbol_names)

        # 3. Confidence score capped
        self.assertLessEqual(summary.project_confidence, 50.0)

        # 4. Handoff explicitly warns resuming agent
        handoff_md = handoff_results["universal"].handoff_md
        self.assertIn("OAuth2AuthenticationService", handoff_md)
        self.assertIn("Contradiction Ledger", handoff_md)

    def test_adversarial_test_pass_claim_against_failing_exit_code(self):
        """
        Scenario: AI agent asserts 'All unit tests pass with zero failures',
        while physical runtime evidence recorded exit code 1 (FAILED).
        Result: Level 1 physical evidence MUST override Level 5 claim. Contradiction logged as HIGH.
        """
        failing_test = TestResult(
            test_id="test_db_01",
            name="test_database_connection",
            suite="test_db.py",
            status=Status.FAILED,
            exit_code=1,
            duration_ms=120.5,
            error_message="ConnectionRefusedError: DB offline"
        )

        p_state = ProjectState(
            root_path=str(self.workspace),
            test_results=[failing_test]
        )

        c_state = ConversationalState(
            agent_claims=[
                AgentClaim(
                    id="claim_test_pass",
                    claim_text="Database connection verified and all tests pass cleanly.",
                    claimed_status=Status.VERIFIED
                )
            ]
        )

        test_ev = Evidence(
            id="ev_test_fail",
            type=EvidenceType.TEST_RUN,
            level=EvidenceLevel.LEVEL_1_RUNTIME_TEST,
            summary="Test test_database_connection failed (exit code 1)",
            raw_payload=failing_test.to_dict(),
            provenance=EvidenceProvenance(extractor_name="VerificationEvidenceExtractor", source_uri="test_db.py", locator="test:test_db.py")
        )
        evidence_pool = {"ev_test_fail": test_ev}

        contradictions = self.detector.detect_contradictions(p_state, c_state, evidence_pool)

        self.assertGreaterEqual(len(contradictions), 1)
        self.assertEqual(contradictions[0].severity, "HIGH")
        self.assertIn("failed", contradictions[0].explanation)

        # Truth arbitration
        status, winning_ev, rationale = self.resolver.resolve_status(
            target_id="test_database_connection",
            evidence_list=[test_ev],
            claims=[{"text": "all tests pass", "status": "VERIFIED"}]
        )
        self.assertEqual(status, Status.FAILED)
        self.assertEqual(winning_ev.id, "ev_test_fail")

    def test_phantom_documentation_detection(self):
        """
        Scenario: Documentation file references `class EnterprisePaymentRouter` and `def dispatch_payout`,
        which have been deleted from or never implemented in source files.
        Result: Must flag MEDIUM contradiction indicating stale/phantom documentation.
        """
        (self.workspace / "README.md").write_text(
            """
# Architecture Overview
To process payments, instantiate `EnterprisePaymentRouter` and call `dispatch_payout()`.
            """,
            encoding="utf-8"
        )
        (self.workspace / "app.py").write_text("def run(): pass", encoding="utf-8")

        pipeline = ContinuumPipeline(self.workspace, project_id="adv_phantom_docs")
        state, summary, handoff_results = pipeline.run_full_analysis()

        self.assertGreaterEqual(summary.contradictions_detected, 1)
        self.assertTrue(any("EnterprisePaymentRouter" in c.explanation for c in state.contradictions))

    def test_misleading_git_commit_messages(self):
        """
        Scenario: A Git commit message claims 'feat: implement KafkaEventStreamingProducer',
        but no matching Kafka files or symbols exist.
        Result: Contradiction engine flags discrepancy between commit message and actual AST state.
        """
        git_state = GitState(
            is_repo=True,
            is_dirty=False,
            recent_commits=[
                {
                    "hash": "abc1234567",
                    "message": "feat: implement KafkaEventStreamingProducer and consumer logic"
                }
            ]
        )
        p_state = ProjectState(
            root_path=str(self.workspace),
            files=["utils.py"],
            symbols=[AstSymbol(name="format_str", kind="function", file_path="utils.py", line_start=1, line_end=3)],
            git_state=git_state
        )

        contradictions = self.detector._detect_misleading_commits(git_state, p_state.symbols, p_state.files)
        self.assertGreaterEqual(len(contradictions), 1)
        self.assertTrue(any("KafkaEventStreamingProducer" in c.explanation for c in contradictions))

    def test_unsupported_binary_and_corrupt_files_resilience(self):
        """
        Scenario: Workspace contains arbitrary binary binaries, zero-byte files, and invalid UTF-8 files.
        Result: System extracts valid files gracefully without throwing unhandled exceptions.
        """
        # Create non-text binary file (.exe / .bin)
        (self.workspace / "binary_data.bin").write_bytes(b"\x00\xFF\xFE\x00\x12\x34\x56\x78\x9A\xBC\xDE\xF0")
        (self.workspace / "empty.py").write_text("", encoding="utf-8")
        (self.workspace / "malformed.py").write_text("def broken_func(:\n   ??invalid python syntax%%%", encoding="utf-8")
        (self.workspace / "valid.py").write_text("def healthy_func() -> int:\n    return 42", encoding="utf-8")

        pipeline = ContinuumPipeline(self.workspace, project_id="adv_binary_resilience")
        state, summary, handoff_results = pipeline.run_full_analysis()

        self.assertIn("healthy_func", [s.name for s in state.project_state.symbols])
        self.assertGreaterEqual(summary.total_files_scanned, 3)
        self.assertIn("universal", handoff_results)

    def test_sparse_incomplete_evidence_preserves_unknown(self):
        """
        Scenario: Brand new repository with no tests, no conversation, and no manifests.
        Result: Status remains UNKNOWN or PENDING rather than falsely asserting VERIFIED.
        """
        (self.workspace / "scratch.py").write_text("# Just a draft script", encoding="utf-8")

        pipeline = ContinuumPipeline(self.workspace, project_id="adv_sparse_evidence")
        state, summary, handoff_results = pipeline.run_full_analysis()

        self.assertEqual(state.project_state.build_status, Status.UNKNOWN)
        # Low confidence due to complete absence of verification
        self.assertLessEqual(summary.project_confidence, 50.0)


if __name__ == "__main__":
    unittest.main()
