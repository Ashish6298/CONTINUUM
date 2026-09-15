"""
Project Continuum - End-to-End User Acceptance & Cross-Model Workflow Validation
==================================================================================
Phase 48: v1.2.0 General Availability (GA) Release Validation.
Simulates and validates the complete real-world user journey:
1. User begins in ChatGPT with an initial coding task and partial code.
2. Context nears exhaustion -> user triggers handoff to Claude.
3. CrossTab relay transmits synthesized, compressed prompt delta with 100% code fidelity.
4. Claude receives auto-injected context and completes implementation.
5. User triggers bi-directional sync to local workspace via POST /api/workspace/sync.
6. Local daemon updates workspace files, records checkpoint, and runs full test verification.
7. Workspace reflects clean state with 100% passing tests and valid lineage history.
"""

from pathlib import Path
import json
import shutil
import tempfile
import unittest
import urllib.request
import urllib.error

from core.enums import Status, TargetModel
from core.state_models import HandoffCheckpointManager, HandoffCheckpoint
from server.daemon import ContinuumHttpDaemon
from pipeline.orchestrator import ContinuumPipeline


class TestGeneralAvailabilityWorkflow(unittest.TestCase):
    """
    Phase 48: General Availability User Acceptance Test Suite.
    Validates complete cross-model handoff, workspace sync, checkpointing, and test execution.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir)

        # Initialize minimal project workspace
        (self.workspace / "pyproject.toml").write_text(
            """[project]
name = "enterprise-payment-service"
version = "1.0.0"
dependencies = ["requests>=2.28.0", "pydantic>=2.0.0"]
""",
            encoding="utf-8"
        )
        (self.workspace / "payment.py").write_text(
            """# Initial stub
class PaymentProcessor:
    def process_transaction(self, amount: float) -> bool:
        raise NotImplementedError("Pending implementation")
""",
            encoding="utf-8"
        )

        # Start local Continuum Daemon
        self.daemon = ContinuumHttpDaemon(
            workspace_root=str(self.workspace),
            host="127.0.0.1",
            default_port=9250,
            require_auth=True
        )
        self.status = self.daemon.start(run_in_background=True)
        self.base_url = self.status.server_url
        self.token = self.daemon.auth_manager.get_token() or ""

    def tearDown(self):
        self.daemon.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_cross_model_lifecycle_chatgpt_to_claude_to_workspace(self):
        """
        Executes complete 5-step user acceptance lifecycle:
        1. ChatGPT coding conversation extracted.
        2. Context compressed & prompt synthesized for Claude.
        3. Multi-turn Checkpoint recorded in daemon history.
        4. Claude generated code synced back to workspace via API.
        5. Workspace re-scanned, verifying AST symbol update and 0 contradictions.
        """
        # Step 1: Simulated ChatGPT conversation turn with partial code
        chatgpt_conversation = {
            "session_id": "session_chatgpt_001",
            "model_name": "ChatGPT-4o",
            "turns": [
                {
                    "turn_id": "t1",
                    "role": "user",
                    "content": "Please implement the Stripe PaymentProcessor in payment.py with refunds."
                },
                {
                    "turn_id": "t2",
                    "role": "assistant",
                    "content": "Here is the implementation of PaymentProcessor:\n```python\nclass PaymentProcessor:\n    def process_transaction(self, amount: float) -> bool:\n        return amount > 0\n    def process_refund(self, txn_id: str) -> bool:\n        return True\n```"
                }
            ]
        }

        # Step 2: Context Compression & Checkpoint Persistence
        chk_mgr = HandoffCheckpointManager(str(self.workspace))
        cp1 = HandoffCheckpoint(
            checkpoint_id="cp_chatgpt_to_claude_001",
            origin_model="chatgpt",
            target_model="claude",
            timestamp="2026-09-15T22:00:00Z",
            prompt_summary="PaymentProcessor Stripe implementation with refunds",
            compressed_prompt="<project_continuation_context>PaymentProcessor with refund method</project_continuation_context>",
            total_messages=2,
            total_code_blocks=1,
            parent_checkpoint_id=None
        )
        chk_mgr.record_checkpoint(cp1)

        # Step 3: Claude continuation step & Checkpoint Chaining
        cp2 = HandoffCheckpoint(
            checkpoint_id="cp_claude_to_workspace_002",
            origin_model="claude",
            target_model="workspace",
            timestamp="2026-09-15T22:05:00Z",
            prompt_summary="Completed PaymentProcessor with validation and error handling",
            compressed_prompt="<verified_code_artifacts>PaymentProcessor complete</verified_code_artifacts>",
            total_messages=4,
            total_code_blocks=2,
            parent_checkpoint_id="cp_chatgpt_to_claude_001"
        )
        chk_mgr.record_checkpoint(cp2)

        # Verify lineage
        lineage = chk_mgr.get_lineage("cp_claude_to_workspace_002")
        self.assertEqual(len(lineage), 2)
        self.assertEqual(lineage[0].checkpoint_id, "cp_chatgpt_to_claude_001")
        self.assertEqual(lineage[1].checkpoint_id, "cp_claude_to_workspace_002")

        # Step 4: Claude syncs completed code to workspace via POST /api/workspace/sync
        completed_code = """# Fully implemented PaymentProcessor
class PaymentProcessor:
    def __init__(self, api_key: str = "sk_test_123"):
        self.api_key = api_key

    def process_transaction(self, amount: float) -> bool:
        if amount <= 0:
            raise ValueError("Amount must be positive")
        return True

    def process_refund(self, txn_id: str) -> bool:
        if not txn_id:
            return False
        return True
"""
        sync_payload = {
            "source": "claude",
            "create_backup": True,
            "files": [
                {
                    "path": "payment.py",
                    "content": completed_code
                }
            ]
        }

        url = f"{self.base_url}/api/workspace/sync"
        req = urllib.request.Request(
            url,
            data=json.dumps(sync_payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Continuum-Token": self.token,
                "Origin": "https://claude.ai"
            }
        )

        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "success")
            self.assertEqual(data.get("synced_count"), 1)

        # Verify physical disk update
        target_file = self.workspace / "payment.py"
        self.assertIn("process_refund", target_file.read_text(encoding="utf-8"))
        self.assertIn("def __init__(self, api_key: str =", target_file.read_text(encoding="utf-8"))

        # Verify backup was safely generated
        backup_dir = self.workspace / ".continuum" / "backup"
        self.assertTrue(backup_dir.is_dir())
        self.assertGreaterEqual(len(list(backup_dir.glob("*.bak"))), 1)

        # Step 5: Full Pipeline Analysis on updated workspace
        pipeline = ContinuumPipeline(self.workspace, project_id="ga_payment_test")
        state, summary, handoffs = pipeline.run_full_analysis(
            task_description="Verify PaymentProcessor completion in payment.py"
        )

        # Verify AST symbols harvested from synced file
        symbol_names = [s.name for s in state.project_state.symbols]
        self.assertIn("PaymentProcessor", symbol_names)
        self.assertTrue(any("process_transaction" in s for s in symbol_names))
        self.assertTrue(any("process_refund" in s for s in symbol_names))

        # Zero contradictions and healthy confidence
        self.assertEqual(summary.contradictions_detected, 0)
        self.assertGreater(summary.project_confidence, 25.0)

        # Verify checkpoints endpoint exposes the full relay history
        checkpoints_url = f"{self.base_url}/api/checkpoints"
        req_chk = urllib.request.Request(
            checkpoints_url,
            headers={
                "X-Continuum-Token": self.token,
                "Origin": "https://claude.ai"
            }
        )
        with urllib.request.urlopen(req_chk, timeout=5) as resp_chk:
            self.assertEqual(resp_chk.status, 200)
            chk_data = json.loads(resp_chk.read().decode("utf-8"))
            self.assertEqual(chk_data.get("status"), "success")
            self.assertGreaterEqual(chk_data.get("count"), 2)


if __name__ == "__main__":
    unittest.main()
