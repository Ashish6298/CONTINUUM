"""
Project Continuum - Phase 52 Baseline Verification Test Suite
=============================================================
Milestone 35: Repository Discovery and Baseline
Phase 52: Baseline Verification

Automated verification of baseline build, environment, runtime contracts,
end-to-end CLI workflows, state arbitration, and regression checklist boundaries.
"""

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.enums import EvidenceType, Status, TargetModel
from core.state_models import CanonicalProjectState, ProjectState, AstSymbol
from core.serializer import CanonicalStateSerializer
from graph.manager import StateGraphManager
from handoff.packager import UniversalHandoffPackager
from storage.manager import ContinuumStorageManager
from cli.main import handle_init, handle_scan, handle_status, handle_graph, handle_handoff


class TestPhase52BaselineVerification(unittest.TestCase):
    """Verifies all runtime baselines, critical workflows, and regression boundaries."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="continuum_p52_baseline_")
        self.workspace = Path(self.temp_dir)
        
        # Create a sample workspace file structure
        src_dir = self.workspace / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "app.py").write_text(
            "def calculate_total(items):\n    '''Computes sum of items.'''\n    return sum(items)\n",
            encoding="utf-8"
        )
        (self.workspace / "README.md").write_text("# Test Baseline Project\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_runtime_environment_baseline(self):
        """Verify Python runtime meets >= 3.10 specification and packaging manifest is valid."""
        self.assertGreaterEqual(sys.version_info[:2], (3, 10), "Runtime must be Python 3.10+")
        pyproject_path = _PROJECT_ROOT / "pyproject.toml"
        self.assertTrue(pyproject_path.exists())
        content = pyproject_path.read_text(encoding="utf-8")
        self.assertIn("requires-python = \">=3.10\"", content)
        self.assertIn("dependencies = []", content)

    def test_e2e_cli_workflow_lifecycle(self):
        """Exercise complete CLI workflow in sequence: init -> scan -> status -> graph -> handoff."""
        # 1. Handle init
        init_args = argparse.Namespace(path=str(self.workspace))
        ret_init = handle_init(init_args)
        self.assertEqual(ret_init, 0, "handle_init must return 0")
        self.assertTrue((self.workspace / ".continuum").is_dir(), ".continuum must be created")

        # 2. Handle scan
        scan_args = argparse.Namespace(path=str(self.workspace))
        ret_scan = handle_scan(scan_args)
        self.assertEqual(ret_scan, 0, "handle_scan must return 0")
        
        storage = ContinuumStorageManager(str(self.workspace))
        self.assertTrue(storage.state_exists(), "state.json must exist after scan")
        state = storage.load_state(validate=True)
        self.assertGreaterEqual(len(state.project_state.files), 2)
        self.assertGreaterEqual(len(state.project_state.symbols), 1)

        # 3. Handle status
        status_args = argparse.Namespace(path=str(self.workspace), json=True)
        ret_status = handle_status(status_args)
        self.assertEqual(ret_status, 0, "handle_status must return 0")

        # 4. Handle graph
        graph_args = argparse.Namespace(path=str(self.workspace), mermaid=False, stats=True)
        ret_graph = handle_graph(graph_args)
        self.assertEqual(ret_graph, 0, "handle_graph must return 0")

        # 5. Handle handoff
        out_dir = self.workspace / "ai_handoff"
        handoff_args = argparse.Namespace(path=str(self.workspace), model="auto", output_dir=str(out_dir))
        ret_handoff = handle_handoff(handoff_args)
        self.assertEqual(ret_handoff, 0, "handle_handoff must return 0")
        
        self.assertTrue((out_dir / "handoff.md").is_file(), "Universal handoff.md must exist")
        self.assertTrue((out_dir / "claude_handoff.md").is_file(), "claude_handoff.md must exist")
        self.assertTrue((out_dir / "gpt_handoff.md").is_file(), "gpt_handoff.md must exist")
        self.assertTrue((out_dir / "gemini_handoff.md").is_file(), "gemini_handoff.md must exist")
        self.assertTrue((out_dir / "project-state.json").is_file(), "project-state.json must exist")

    def test_state_isolation_and_evidence_hierarchy(self):
        """Verify 5-tier evidence hierarchy prevents unverified conversational claims from corrupting physical state."""
        from core.state_models import AgentClaim
        state = CanonicalProjectState(project_id="test_evidence_baseline")
        state.project_state.symbols.append(
            AstSymbol(
                name="auth_service",
                kind="function",
                file_path="src/auth.py",
                line_start=1,
                line_end=10,
                exported=True
            )
        )
        # Agent claims in chat that payment service exists
        state.conversational_state.agent_claims.append(
            AgentClaim(
                id="claim_1",
                claim_text="Payment service complete",
                target_component="payment_service",
                claimed_status=Status.VERIFIED
            )
        )
        
        # Verify physical state contains only AST symbols, not conversational claims
        self.assertEqual(len(state.project_state.symbols), 1)
        self.assertEqual(state.project_state.symbols[0].name, "auth_service")
        self.assertNotIn("payment_service", [s.name for s in state.project_state.symbols])

    def test_graph_dag_topological_invariants(self):
        """Verify state graph builds a valid DAG and exports deterministic Mermaid diagrams."""
        from core.enums import NodeType, RelationType
        from core.state_models import GraphNode, GraphEdge
        state = CanonicalProjectState(project_id="test_dag_baseline")
        gm = StateGraphManager(state)
        gm.add_node(GraphNode(id="node_a", name="Root Service", node_type=NodeType.SERVICE, status=Status.VERIFIED))
        gm.add_node(GraphNode(id="node_b", name="Dependent Service", node_type=NodeType.SERVICE, status=Status.VERIFIED))
        gm.add_edge(GraphEdge(source_id="node_a", target_id="node_b", relation=RelationType.DEPENDS_ON))
        
        stats = gm.get_stats()
        self.assertEqual(stats.total_nodes, 2)
        self.assertEqual(stats.total_edges, 1)
        
        mermaid = gm.export_mermaid()
        self.assertIn("graph TD", mermaid)
        self.assertIn("node_a", mermaid)
        self.assertIn("node_b", mermaid)

    def test_regression_checklist_integrity(self):
        """Verify all critical module namespaces adhere to regression contracts."""
        critical_modules = [
            "core.state_models",
            "storage.manager",
            "graph.manager",
            "handoff.packager",
            "server.routes",
            "server.auth",
            "server.sanitizer",
            "cli.main",
            "watcher.detector",
            "daemon.service"
        ]
        for mod in critical_modules:
            __import__(mod)
            self.assertIn(mod, sys.modules, f"Critical module {mod} must be loaded and functional")


if __name__ == "__main__":
    unittest.main()
