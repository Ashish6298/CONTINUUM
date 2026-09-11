"""
Project Continuum - End-to-End Integration & Polyglot Validation Tests
======================================================================
Milestone 8 - Phase 19: End-to-End Integration & Polyglot Validation.
Validates the complete Continuum pipeline on:
1. Pure Python Backend workspace (pyproject.toml, pytest, AST symbols).
2. TypeScript / React Frontend workspace (package.json, interfaces, exports).
3. Polyglot Full-Stack workspace (Python backend + TS frontend + Dockerfile + Git history).
4. Contradiction & Claim Resolution across the full pipeline.
5. Multi-model handoff generation invariance (Claude, Codex/GPT, Gemini, Local LLM).
"""

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from core.enums import Status, TargetModel
from core.state_models import TestResult
from pipeline.orchestrator import ContinuumPipeline


class TestEndToEndPipeline(unittest.TestCase):
    """
    End-to-End integration test suite executing the complete Continuum pipeline:
    Workspace -> Evidence Extraction -> Evidence Resolution -> Contradiction Detection
    -> Confidence Calculation -> Canonical State Graph -> Context Selection -> Model Handoff.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_pure_python_backend_pipeline(self):
        """
        Validates pipeline execution on a Python repository with pyproject.toml,
        classes, functions, and unit test execution evidence.
        """
        # Create Python project files
        (self.workspace / "pyproject.toml").write_text(
            """
[project]
name = "auth-service"
version = "2.1.0"
dependencies = ["bcrypt>=4.0.0", "jwt>=1.0.0"]
            """,
            encoding="utf-8"
        )
        (self.workspace / "auth.py").write_text(
            """
import bcrypt

class AuthService:
    def authenticate(self, user: str, token: str) -> bool:
        # TODO: Implement multi-factor auth
        return True

    def revoke_token(self, token_id: str) -> None:
        pass
            """,
            encoding="utf-8"
        )

        test_result = TestResult(
            test_id="test_auth_01",
            name="test_authenticate",
            suite="test_auth.py",
            status=Status.VERIFIED,
            exit_code=0,
            duration_ms=45.2
        )

        pipeline = ContinuumPipeline(self.workspace, project_id="test_python_auth")
        state, summary, handoff_results = pipeline.run_full_analysis(
            explicit_verification_results=[test_result],
            task_description="Implement multi-factor auth in AuthService",
            token_budget=1500
        )

        # Assertions on pipeline summary
        self.assertEqual(summary.project_id, "test_python_auth")
        self.assertIn("Python", summary.languages_detected)
        self.assertGreaterEqual(summary.total_files_scanned, 2)
        self.assertGreaterEqual(summary.total_symbols_extracted, 3) # AuthService, authenticate, revoke_token
        self.assertGreater(summary.project_confidence, 30.0)
        self.assertGreater(summary.graph_nodes_count, 0)
        self.assertEqual(summary.contradictions_detected, 0)

        # Assertions on generated handoffs
        self.assertIn("universal", handoff_results)
        self.assertIn("claude", handoff_results)
        self.assertIn("codex", handoff_results)
        self.assertIn("gemini", handoff_results)
        self.assertIn("local_llm", handoff_results)

        claude_handoff = handoff_results["claude"]["handoff.md"]
        claude_context = handoff_results["claude"]["project-context.md"]
        self.assertIn("<system_directives>", claude_handoff)
        self.assertIn("AuthService", claude_context)

        codex_md = handoff_results["codex"]["handoff.md"]
        self.assertIn("# Project Continuum", codex_md)

    def test_typescript_frontend_pipeline(self):
        """
        Validates pipeline execution on a TypeScript frontend with package.json,
        interfaces, functions, and exported components.
        """
        (self.workspace / "package.json").write_text(
            json.dumps({
                "name": "dashboard-ui",
                "version": "1.0.0",
                "dependencies": {"react": "^18.2.0", "axios": "^1.4.0"},
                "devDependencies": {"typescript": "^5.0.0"}
            }),
            encoding="utf-8"
        )
        (self.workspace / "Dashboard.tsx").write_text(
            """
import React from 'react';

export interface UserProfile {
    id: string;
    email: string;
    role: string;
}

export const DashboardView: React.FC = () => {
    return <div>Dashboard</div>;
};

export function fetchUserData(userId: string): Promise<UserProfile> {
    return Promise.resolve({ id: userId, email: "user@test.com", role: "admin" });
}
            """,
            encoding="utf-8"
        )

        pipeline = ContinuumPipeline(self.workspace, project_id="test_ts_dashboard")
        state, summary, handoff_results = pipeline.run_full_analysis(
            task_description="Fix fetchUserData error handling",
            token_budget=2000
        )

        self.assertIn("TypeScript", summary.languages_detected)
        self.assertGreaterEqual(summary.total_files_scanned, 2)
        self.assertGreaterEqual(summary.total_symbols_extracted, 3) # UserProfile, DashboardView, fetchUserData
        self.assertIn("universal", handoff_results)

        gemini_context = handoff_results["gemini"]["project-context.md"]
        self.assertIn("DashboardView", gemini_context)
        self.assertIn("UserProfile", gemini_context)

    def test_polyglot_fullstack_with_conversation_contradiction(self):
        """
        Validates a full-stack polyglot project (Python + TS + Dockerfile)
        with an AI chat claim that contradicts physical reality.
        """
        # 1. Physical workspace setup
        (self.workspace / "package.json").write_text(
            json.dumps({"name": "fullstack-app", "dependencies": {"express": "^4.18.2"}}),
            encoding="utf-8"
        )
        (self.workspace / "server.ts").write_text(
            """
export function startServer(port: number) {
    console.log(`Server on ${port}`);
}
            """,
            encoding="utf-8"
        )
        (self.workspace / "worker.py").write_text(
            """
def process_task(task_id: str) -> None:
    pass
            """,
            encoding="utf-8"
        )
        (self.workspace / "Dockerfile").write_text("FROM node:18-alpine\nWORKDIR /app", encoding="utf-8")

        # 2. Ingest conversation transcript where AI falsely claims PaymentGateway is complete
        chat_transcript = {
            "session_id": "polyglot_session_001",
            "model_name": "Claude-3.5-Sonnet",
            "turns": [
                {
                    "turn_id": "t1",
                    "role": "user",
                    "content": "Please implement Stripe PaymentGateway and verify tests."
                },
                {
                    "turn_id": "t2",
                    "role": "assistant",
                    "content": "I have completed PaymentGateway and all payment tests are passing with 100% success."
                }
            ]
        }

        pipeline = ContinuumPipeline(self.workspace, project_id="test_fullstack_contradiction")
        state, summary, handoff_results = pipeline.run_full_analysis(
            conversation_input=chat_transcript,
            task_description="Verify PaymentGateway implementation"
        )

        # 3. Assert Contradiction Detection
        self.assertGreaterEqual(summary.contradictions_detected, 1)
        self.assertTrue(any("PaymentGateway" in c.claim_text or "missing" in c.explanation.lower() or "payment" in c.explanation.lower() for c in state.contradictions))

        # 4. Strict 3-State Separation Check
        # Physical ProjectState must NOT contain PaymentGateway
        found_symbols = [s.name for s in state.project_state.symbols]
        self.assertNotIn("PaymentGateway", found_symbols)

        # ConversationalState MUST contain the agent claim
        self.assertTrue(any("PaymentGateway" in cl.claim_text for cl in state.conversational_state.agent_claims))

        # 5. Handoff package must explicitly warn next agent of contradiction
        universal_pkg = handoff_results["universal"]
        handoff_md = universal_pkg.handoff_md
        self.assertIn("Contradiction Ledger", handoff_md)
        self.assertIn("PaymentGateway", handoff_md)


if __name__ == "__main__":
    unittest.main()
