"""
Project Continuum - Test Suite for Phase 14 (Universal Handoff Package Generation)
===================================================================================
Milestone 6 - Phase 14.
Validates:
1. Complete package generation (project-state.json, project-context.md, handoff.md, evidence/).
2. Strict distinction between verified reality, unverified claims, contradictions, and blockers.
3. Accurate NextActionRecommendation and TacticalTask continuation briefings.
4. Atomic filesystem persistence with directory structuring.
5. JSON Schema compliance of generated project-state.json.
"""

import json
import os
from pathlib import Path
import tempfile
import unittest

from core.enums import NodeType, RelationType, Status
from core.evidence import Evidence
from core.schema import validate_canonical_state_dict
from core.state_models import (
    AgentClaim,
    AgentExecutionState,
    ArchitecturalDecision,
    AstSymbol,
    CanonicalProjectState,
    ContradictionRecord,
    ConversationalState,
    GitState,
    GraphEdge,
    GraphNode,
    NextActionRecommendation,
    ProjectState,
    Requirement,
    TacticalTask,
    TestResult,
    UnresolvedQuestion,
)
from context.models import TaskContext
from handoff.models import HandoffPackage
from handoff.packager import UniversalHandoffPackager


class TestHandoffPackager(unittest.TestCase):
    """Test suite for UniversalHandoffPackager and HandoffPackage."""

    def setUp(self):
        self.packager = UniversalHandoffPackager()

        # Build a rich, realistic CanonicalProjectState
        self.state = CanonicalProjectState(
            schema_version="1.0.0",
            project_id="proj_continuum_demo",
            project_state=ProjectState(
                root_path="/workspace/continuum",
                detected_languages=["python", "typescript"],
                files=["src/auth.py", "src/crypto.py", "tests/test_auth.py"],
                symbols=[
                    AstSymbol(name="AuthService", kind="class", file_path="src/auth.py", line_start=1, line_end=50),
                    AstSymbol(name="verify_token", kind="function", file_path="src/crypto.py", line_start=10, line_end=35)
                ],
                git_state=GitState(
                    is_repo=True,
                    branch="feature/handoff-pkg",
                    head_commit="a1b2c3d4",
                    is_dirty=True,
                    staged_files=["src/auth.py"],
                    unstaged_files=["src/crypto.py"],
                    untracked_files=[]
                ),
                test_results=[
                    TestResult(test_id="t1", name="test_login_success", suite="test_auth.py", status=Status.VERIFIED, exit_code=0, duration_ms=4.5),
                    TestResult(test_id="t2", name="test_refresh_expired", suite="test_auth.py", status=Status.FAILED, exit_code=1, duration_ms=6.2, error_message="ExpiredSignature")
                ],
                build_status=Status.VERIFIED
            ),
            conversational_state=ConversationalState(
                user_requirements=[
                    Requirement(id="req_01", title="OAuth2 Authentication", description="Provide JWT token login and refresh endpoint.")
                ],
                architectural_decisions=[
                    ArchitecturalDecision(id="dec_01", title="Use RS256 Asymmetric Keys", rationale="Stateless token validation across microservices.", constraints=["Must not store raw private keys in plain text"])
                ],
                agent_claims=[
                    AgentClaim(id="claim_01", claim_text="Token refresh is 100% complete and working", target_component="AuthService", claimed_status=Status.VERIFIED, source_agent="claude-3-5-sonnet")
                ],
                unresolved_questions=[
                    UnresolvedQuestion(id="q_01", question="Should refresh tokens expire after 7 or 14 days?", blocking=False)
                ]
            ),
            agent_execution_state=AgentExecutionState(
                agent_id="agent_prev_42",
                model_name="claude-3-5-sonnet",
                active_tasks=[
                    TacticalTask(id="task_jwt", title="Fix token refresh expiry handling", status=Status.IN_PROGRESS, target_files=["src/auth.py"], target_symbols=["verify_token"], notes="Working on ExpiredSignature edge case")
                ],
                next_action=NextActionRecommendation(
                    action_type="FIX_TEST_FAILURE",
                    target_uri="src/auth.py:verify_token",
                    description="Fix ExpiredSignature error thrown in test_refresh_expired",
                    prerequisites=["src/crypto.py"]
                )
            ),
            graph_nodes={
                "auth_svc": GraphNode(id="auth_svc", name="AuthService", node_type=NodeType.SERVICE, status=Status.IN_PROGRESS, confidence_score=75.0),
                "crypto_mod": GraphNode(id="crypto_mod", name="CryptoUtils", node_type=NodeType.MODULE, status=Status.VERIFIED, confidence_score=95.0)
            },
            graph_edges=[
                GraphEdge(source_id="auth_svc", target_id="crypto_mod", relation=RelationType.IMPORTS)
            ],
            contradictions=[
                ContradictionRecord(
                    id="contra_01",
                    severity="HIGH",
                    claim_id="claim_01",
                    claim_text="Token refresh is 100% complete and working",
                    explanation="Agent claimed refresh is complete, but test_refresh_expired failed with exit code 1",
                    resolved=False
                )
            ]
        )

    def test_universal_package_generation_structure(self):
        """
        Verifies that generate_package constructs all required package components:
        project-state.json, project-context.md, handoff.md, and evidence files.
        """
        package = self.packager.generate_package(self.state)

        self.assertIsInstance(package, HandoffPackage)
        self.assertEqual(package.project_id, "proj_continuum_demo")

        # 1. project-state.json
        self.assertTrue(len(package.project_state_json) > 0)
        parsed_state = json.loads(package.project_state_json)
        self.assertEqual(parsed_state["project_id"], "proj_continuum_demo")

        # Validate Schema Compliance
        is_valid, errors = validate_canonical_state_dict(parsed_state)
        self.assertTrue(is_valid, f"Schema validation failed: {errors}")

        # 2. project-context.md
        self.assertIn("Verified Project Context", package.project_context_md)
        self.assertIn("AuthService", package.project_context_md)
        self.assertIn("**Passing Tests:** 1", package.project_context_md)
        self.assertIn("**Failing Tests:** 1", package.project_context_md)

        # 3. handoff.md
        self.assertIn("# Project Continuum — Agent Handoff Briefing", package.handoff.md if hasattr(package, 'handoff') else package.handoff_md)
        self.assertIn("Fix token refresh expiry handling", package.handoff_md)
        self.assertIn("FIX_TEST_FAILURE", package.handoff_md)
        self.assertIn("Agent claimed refresh is complete, but test_refresh_expired failed", package.handoff_md)

        # 4. evidence files
        self.assertIn("test_results.json", package.evidence_files)
        self.assertIn("contradictions.json", package.evidence_files)
        self.assertIn("symbols_manifest.json", package.evidence_files)
        self.assertIn("evidence_manifest.json", package.evidence_files)

    def test_package_distinguishes_verified_vs_claims_and_contradictions(self):
        """
        Verifies that handoff.md explicitly distinguishes physical proof from agent claims
        and flags contradictions and blockers clearly.
        """
        package = self.packager.generate_package(self.state)

        # Claims are marked as unverified / Level 5
        self.assertIn("Token refresh is 100% complete and working", package.handoff_md)
        self.assertIn("Unverified Agent Claims", package.handoff_md)

        # Contradictions are explicitly flagged as active blockers
        self.assertIn("[ACTIVE BLOCKER]", package.handoff_md)
        self.assertIn("ExpiredSignature", package.handoff_md)

    def test_package_atomic_save_to_directory(self):
        """
        Verifies saving the complete package to a target directory on disk.
        """
        package = self.packager.generate_package(self.state)

        with tempfile.TemporaryDirectory() as temp_dir:
            written_map = package.save_to_directory(temp_dir)

            base = Path(temp_dir)
            self.assertTrue((base / "project-state.json").exists())
            self.assertTrue((base / "project-context.md").exists())
            self.assertTrue((base / "handoff.md").exists())
            self.assertTrue((base / "evidence" / "test_results.json").exists())
            self.assertTrue((base / "evidence" / "contradictions.json").exists())
            self.assertTrue((base / "evidence" / "symbols_manifest.json").exists())

            # Read back and verify JSON integrity
            with open(base / "evidence" / "test_results.json", "r", encoding="utf-8") as f:
                saved_tests = json.load(f)
                self.assertEqual(len(saved_tests), 2)
                self.assertEqual(saved_tests[1]["error_message"], "ExpiredSignature")


if __name__ == "__main__":
    unittest.main()
