"""
Project Continuum - Test Suite for Phase 15 (Model-Specific Handoff Adapters)
==============================================================================
Milestone 6 - Phase 15.
Validates:
1. ClaudeAdapter produces XML-tagged semantic boundaries.
2. CodexGptAdapter produces clean Markdown with code blocks and task lists.
3. GeminiAdapter produces hierarchical multi-tier ontological context.
4. LocalModelAdapter produces compact token-dense briefings.
5. All 4 adapters comply with IModelAdapter protocol.
6. Semantic Invariance Guarantee: Ground truth facts (verified components,
   failing tests, active contradictions, constraints, next actions) are
   identically preserved across ALL adapters without distortion.
"""

import json
import unittest

from core.enums import NodeType, RelationType, Status, TargetModel
from core.interfaces import IModelAdapter
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
)
from handoff.adapters import (
    ClaudeAdapter,
    CodexGptAdapter,
    GeminiAdapter,
    LocalModelAdapter,
    get_adapter_for_model,
)


class TestModelAdapters(unittest.TestCase):
    """Test suite for Phase 15 Model-Specific Handoff Adapters."""

    def setUp(self):
        # Build canonical benchmark state with rich ground truth & contradictions
        self.state = CanonicalProjectState(
            schema_version="1.0.0",
            project_id="proj_multi_model_benchmark",
            project_state=ProjectState(
                root_path="/workspace/continuum",
                detected_languages=["python", "rust"],
                files=["src/auth.py", "src/crypto.rs"],
                symbols=[
                    AstSymbol(name="AuthService", kind="class", file_path="src/auth.py", line_start=1, line_end=60),
                    AstSymbol(name="verify_signature", kind="function", file_path="src/crypto.rs", line_start=1, line_end=25)
                ],
                git_state=GitState(
                    is_repo=True,
                    branch="main",
                    head_commit="f9e8d7c6",
                    is_dirty=False
                ),
                test_results=[
                    TestResult(test_id="t1", name="test_auth_success", suite="test_auth.py", status=Status.VERIFIED, exit_code=0, duration_ms=3.2),
                    TestResult(test_id="t2", name="test_signature_failure", suite="test_crypto.rs", status=Status.FAILED, exit_code=1, duration_ms=4.8, error_message="InvalidPublicKey")
                ],
                build_status=Status.VERIFIED
            ),
            conversational_state=ConversationalState(
                user_requirements=[
                    Requirement(id="req_01", title="Cryptographic verification", description="Validate RS256 token signatures.")
                ],
                architectural_decisions=[
                    ArchitecturalDecision(
                        id="dec_01",
                        title="Asymmetric Encryption Standard",
                        rationale="Zero shared secret exposure across edge nodes.",
                        constraints=["Enforce minimum 2048-bit key", "Never persist raw private keys"]
                    )
                ],
                agent_claims=[
                    AgentClaim(id="claim_01", claim_text="Cryptography module passed all tests", target_component="CryptoUtils", claimed_status=Status.VERIFIED, source_agent="gpt-4o")
                ]
            ),
            agent_execution_state=AgentExecutionState(
                agent_id="agent_source_10",
                model_name="claude-3-5-sonnet",
                active_tasks=[
                    TacticalTask(id="task_01", title="Fix InvalidPublicKey assertion in crypto", status=Status.IN_PROGRESS, target_files=["src/crypto.rs"])
                ],
                next_action=NextActionRecommendation(
                    action_type="FIX_TEST_FAILURE",
                    target_uri="src/crypto.rs:verify_signature",
                    description="Resolve InvalidPublicKey error in test_signature_failure"
                )
            ),
            graph_nodes={
                "auth_svc": GraphNode(id="auth_svc", name="AuthService", node_type=NodeType.SERVICE, status=Status.VERIFIED, confidence_score=90.0),
                "crypto_svc": GraphNode(id="crypto_svc", name="CryptoService", node_type=NodeType.SERVICE, status=Status.IN_PROGRESS, confidence_score=50.0)
            },
            contradictions=[
                ContradictionRecord(
                    id="contra_01",
                    severity="HIGH",
                    claim_id="claim_01",
                    claim_text="Cryptography module passed all tests",
                    explanation="Agent claimed crypto passed all tests, but test_signature_failure failed with exit code 1",
                    resolved=False
                )
            ]
        )

        self.adapters = [
            ClaudeAdapter(),
            CodexGptAdapter(),
            GeminiAdapter(),
            LocalModelAdapter(),
        ]

    def test_protocol_compliance_and_target_models(self):
        """All adapters must satisfy the IModelAdapter Protocol."""
        for adapter in self.adapters:
            self.assertIsInstance(adapter, IModelAdapter)
            self.assertIn(adapter.target_model, [TargetModel.CLAUDE, TargetModel.CODEX_GPT, TargetModel.GEMINI, TargetModel.LOCAL_LLM])

    def test_claude_adapter_xml_tagging(self):
        """ClaudeAdapter must generate semantic XML tags."""
        adapter = ClaudeAdapter()
        res = adapter.generate_handoff(self.state)

        self.assertIn("<project_metadata>", res["project-context.md"])
        self.assertIn("<verified_architecture>", res["project-context.md"])
        self.assertIn("<system_directives>", res["handoff.md"])
        self.assertIn("<active_tasks>", res["handoff.md"])
        self.assertIn("<active_blockers_and_contradictions>", res["handoff.md"])
        self.assertIn("Fix InvalidPublicKey assertion in crypto", res["handoff.md"])

    def test_codex_gpt_adapter_markdown_and_codeblocks(self):
        """CodexGptAdapter must generate markdown headers and checklists."""
        adapter = CodexGptAdapter()
        res = adapter.generate_handoff(self.state)

        self.assertIn("# Project Continuum — Verified Context for Codex/GPT", res["project-context.md"])
        self.assertIn("```json", res["project-context.md"])
        self.assertIn("## 📋 Active Tasks & Next Steps", res["handoff.md"])
        self.assertIn("FIX_TEST_FAILURE", res["handoff.md"])
        self.assertIn("- ❌ **[HIGH BLOCKER]**", res["handoff.md"])

    def test_gemini_adapter_hierarchical_structure(self):
        """GeminiAdapter must generate multi-tier hierarchical knowledge topology."""
        adapter = GeminiAdapter()
        res = adapter.generate_handoff(self.state)

        self.assertIn("## Tier 1: Ground Truth Project Topology", res["project-context.md"])
        self.assertIn("## Tier 2: Empirical Verification & Evidence Matrix", res["project-context.md"])
        self.assertIn("## 1. Tactical Execution Queue", res["handoff.md"])
        self.assertIn("## 3. Discrepancy & Contradiction Registry", res["handoff.md"])

    def test_local_model_adapter_compactness(self):
        """LocalModelAdapter must produce concise, token-dense context."""
        adapter = LocalModelAdapter()
        res = adapter.generate_handoff(self.state)

        self.assertIn("# Context:", res["project-context.md"])
        self.assertIn("# Handoff | PrevAgent:", res["handoff.md"])
        self.assertIn("BLOCKER [HIGH]:", res["handoff.md"])
        self.assertIn("FIX_TEST_FAILURE", res["handoff.md"])

    def test_factory_function_resolution(self):
        """get_adapter_for_model must resolve to the correct adapter class."""
        self.assertIsInstance(get_adapter_for_model(TargetModel.CLAUDE), ClaudeAdapter)
        self.assertIsInstance(get_adapter_for_model(TargetModel.CODEX_GPT), CodexGptAdapter)
        self.assertIsInstance(get_adapter_for_model(TargetModel.GEMINI), GeminiAdapter)
        self.assertIsInstance(get_adapter_for_model(TargetModel.LOCAL_LLM), LocalModelAdapter)

    def test_cross_adapter_semantic_invariance(self):
        """
        CRITICAL TEST:
        Every adapter, despite syntax differences (XML vs Markdown vs Hierarchical vs Compact),
        MUST preserve 100% of the underlying verified facts:
        1. Verified component name ('AuthService')
        2. Failing test name ('test_signature_failure')
        3. Contradiction explanation / blocker
        4. Hard constraint ('Never persist raw private keys')
        5. Next actionable task ('src/crypto.rs:verify_signature' or 'FIX_TEST_FAILURE')
        """
        for adapter in self.adapters:
            handoff_dict = adapter.generate_handoff(self.state)
            combined_text = handoff_dict["project-context.md"] + "\n" + handoff_dict["handoff.md"]

            # 1. Verified component
            self.assertIn("AuthService", combined_text, f"{adapter.target_model} missing AuthService")

            # 2. Failing test
            self.assertIn("test_signature_failure", combined_text, f"{adapter.target_model} missing failing test")

            # 3. Contradiction / Blocker
            self.assertTrue(
                ("test_signature_failure failed" in combined_text) or ("InvalidPublicKey" in combined_text) or ("HIGH" in combined_text),
                f"{adapter.target_model} missing blocker contradiction"
            )

            # 4. Inviolable constraint
            self.assertIn("Never persist raw private keys", combined_text, f"{adapter.target_model} missing constraint")

            # 5. Next Action
            self.assertTrue(
                ("FIX_TEST_FAILURE" in combined_text) or ("verify_signature" in combined_text),
                f"{adapter.target_model} missing next action"
            )

            # 6. JSON state validity
            is_valid, errs = validate_canonical_state_dict(json.loads(handoff_dict["project-state.json"]))
            self.assertTrue(is_valid, f"{adapter.target_model} generated invalid JSON schema: {errs}")


if __name__ == "__main__":
    unittest.main()
