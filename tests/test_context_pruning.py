"""
Project Continuum - Test Suite for Phase 13 (Context Pruning & Token Budget Optimization)
==========================================================================================
Milestone 5 - Phase 13.
Validates:
1. Small token budget pruning (prioritizing Tier 1 constraints & blockers).
2. Large token budget retaining all project details (0% omission).
3. Guarantee that active architectural constraints are NEVER silently omitted.
4. Detailed omission reporting in the audit ledger.
5. Accurate measurement of token reduction percentage.
"""

import unittest

from core.enums import NodeType, RelationType, Status
from core.state_models import (
    ArchitecturalDecision,
    AstSymbol,
    CanonicalProjectState,
    ContradictionRecord,
    GraphNode,
    TestResult,
)
from context.models import TaskContext
from context.pruner import ContextPruner


class TestContextPruning(unittest.TestCase):
    """Test suite for ContextPruner."""

    def setUp(self):
        self.pruner = ContextPruner()

        # Build a rich synthetic TaskContext
        self.task_context = TaskContext(
            task_description="Implement OAuth2 token refresh with RS256 signing",
            primary_nodes=[
                GraphNode(id="auth_svc", name="AuthService", node_type=NodeType.SERVICE, status=Status.IN_PROGRESS, confidence_score=60.0),
                GraphNode(id="oauth_jwt", name="OAuthTokenManager", node_type=NodeType.API, status=Status.VERIFIED, confidence_score=85.0),
            ],
            dependency_nodes=[
                GraphNode(id="db_pool", name="DatabasePool", node_type=NodeType.SERVICE, status=Status.VERIFIED),
                GraphNode(id="redis_cache", name="RedisTokenCache", node_type=NodeType.SERVICE, status=Status.VERIFIED),
                GraphNode(id="crypto_lib", name="CryptoUtils", node_type=NodeType.MODULE, status=Status.VERIFIED),
            ],
            relevant_symbols=[
                AstSymbol(name="AuthService", kind="class", file_path="auth.py", line_start=1, line_end=80),
                AstSymbol(name="rotate_token", kind="function", file_path="auth.py", line_start=85, line_end=120),
                AstSymbol(name="validate_rs256_signature", kind="function", file_path="crypto.py", line_start=1, line_end=40),
            ],
            relevant_tests=[
                TestResult(
                    test_id="t1",
                    name="test_refresh_expired_token",
                    suite="test_auth.py",
                    status=Status.FAILED,
                    exit_code=1,
                    duration_ms=12.0,
                    error_message="SignatureVerificationError: Invalid public key"
                ),
                TestResult(
                    test_id="t2",
                    name="test_jwt_encode_decode",
                    suite="test_auth.py",
                    status=Status.VERIFIED,
                    exit_code=0,
                    duration_ms=5.0
                )
            ],
            active_constraints=[
                "NEVER store unencrypted private keys on disk",
                "Enforce RS256 algorithm with minimum 2048-bit RSA key",
                "Refresh token lifetime must not exceed 7 calendar days"
            ],
            relevant_decisions=[
                ArchitecturalDecision(
                    id="dec_auth_01",
                    title="OAuth2 RS256 Standard",
                    rationale="Selected asymmetric key pairs to allow stateless token validation across edge microservices."
                )
            ],
            known_blockers=[
                ContradictionRecord(
                    id="contra_01",
                    severity="HIGH",
                    claim_text="Auth verified",
                    explanation="test_refresh_expired_token failed with exit code 1",
                    resolved=False
                )
            ],
            omitted_node_count=15
        )

    def test_small_token_budget_pruning(self):
        """
        Under a tight token budget (e.g. 150 tokens), ContextPruner must prune
        Tier 5 (Decisions) and Tier 4 (Symbols), while preserving Tier 1 (Constraints & Blockers).
        """
        result = self.pruner.prune_to_budget(self.task_context, token_budget=150)

        self.assertLessEqual(result.estimated_tokens_after, 250)  # Close to budget + audit footer
        self.assertGreater(result.reduction_percentage, 20.0)
        self.assertTrue(result.constraint_preservation_guarantee)

        # Critical constraints MUST be present
        self.assertIn("NEVER store unencrypted private keys on disk", result.formatted_prompt)
        self.assertIn("Enforce RS256 algorithm", result.formatted_prompt)
        self.assertIn("Active Blockers", result.formatted_prompt)

        # Omission audit must report pruned items
        self.assertGreater(len(result.omitted_items), 0)
        self.assertIn("Omitted Items due to budget constraints", result.formatted_prompt)

    def test_large_token_budget_retains_all(self):
        """
        Under a large token budget (e.g. 5,000 tokens), 100% of information is retained with 0% reduction.
        """
        result = self.pruner.prune_to_budget(self.task_context, token_budget=5000)

        self.assertEqual(result.reduction_percentage, 0.0)
        self.assertEqual(len(result.omitted_items), 0)
        self.assertEqual(result.retained_sections, ["all"])
        self.assertIn("OAuth2 RS256 Standard", result.formatted_prompt)
        self.assertIn("validate_rs256_signature", result.formatted_prompt)

    def test_critical_constraints_never_silently_dropped(self):
        """
        Even under extreme budget pressure (e.g. 50 tokens), active constraints
        must be retained with explicit constraint guarantee flag.
        """
        result = self.pruner.prune_to_budget(self.task_context, token_budget=50)

        self.assertTrue(result.constraint_preservation_guarantee)
        self.assertIn("NEVER store unencrypted private keys", result.formatted_prompt)

    def test_task_context_prune_convenience_method(self):
        """
        Verifies task_context.prune(budget) shortcut.
        """
        pruned_res = self.task_context.prune(token_budget=250)
        self.assertIsNotNone(pruned_res)
        self.assertTrue(pruned_res.constraint_preservation_guarantee)


if __name__ == "__main__":
    unittest.main()
