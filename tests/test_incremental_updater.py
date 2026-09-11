"""
Project Continuum - Test Suite for Phase 16 (Filesystem Observation & Incremental State Updates)
================================================================================================
Milestone 7 - Phase 16.
Validates:
1. WorkspaceChangeDetector detects file creations, modifications, and deletions.
2. IncrementalStateUpdater re-extracts AST symbols for modified files in-place.
3. IncrementalStateUpdater cleans up removed symbols when files are deleted.
4. Downstream dependency invalidation & STALE status propagation via StateGraphManager.
5. Large batch change fallback to full scan.
"""

import json
from pathlib import Path
import tempfile
import time
import unittest

from core.enums import NodeType, RelationType, Status
from core.state_models import (
    AstSymbol,
    CanonicalProjectState,
    GraphEdge,
    GraphNode,
    ProjectState,
)
from graph.manager import StateGraphManager
from watcher.detector import WorkspaceChangeDetector
from watcher.models import ChangeType, FileChangeEvent
from watcher.updater import IncrementalStateUpdater


class TestIncrementalStateUpdates(unittest.TestCase):
    """Test suite for Phase 16 Filesystem Observation & Incremental State Updates."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

        # Create initial workspace structure
        self.src_dir = self.workspace / "src"
        self.src_dir.mkdir(parents=True, exist_ok=True)

        self.auth_file = self.src_dir / "auth.py"
        self.auth_file.write_text(
            "class AuthService:\n    def login(self, username: str):\n        return True\n",
            encoding="utf-8"
        )

        self.api_file = self.src_dir / "api.py"
        self.api_file.write_text(
            "def handle_login_route():\n    return 'ok'\n",
            encoding="utf-8"
        )

        # Initialize detector and state
        self.detector = WorkspaceChangeDetector(str(self.workspace))
        self.detector.initialize_baseline()

        self.updater = IncrementalStateUpdater(str(self.workspace))

        # Build initial CanonicalProjectState
        self.state = CanonicalProjectState(
            project_id="proj_watch_test",
            project_state=ProjectState(
                root_path=str(self.workspace),
                detected_languages=["python"],
                files=["src/auth.py", "src/api.py"],
                symbols=[
                    AstSymbol(name="AuthService", kind="class", file_path="src/auth.py", line_start=1, line_end=3),
                    AstSymbol(name="login", kind="method", file_path="src/auth.py", line_start=2, line_end=3),
                    AstSymbol(name="handle_login_route", kind="function", file_path="src/api.py", line_start=1, line_end=2)
                ],
                build_status=Status.VERIFIED
            ),
            graph_nodes={
                "auth": GraphNode(id="auth", name="auth", node_type=NodeType.MODULE, status=Status.VERIFIED, confidence_score=100.0),
                "api": GraphNode(id="api", name="api", node_type=NodeType.SERVICE, status=Status.VERIFIED, confidence_score=90.0)
            },
            graph_edges=[
                GraphEdge(source_id="api", target_id="auth", relation=RelationType.DEPENDS_ON)
            ]
        )

        self.graph_manager = StateGraphManager(self.state)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_file_modification_and_symbol_re_extraction(self):
        """
        Modifying auth.py to add a new method 'logout' should be detected and re-extracted
        into canonical state symbols without affecting api.py symbols.
        """
        # Sleep slightly to guarantee mtime change on all OS platforms
        time.sleep(0.05)
        self.auth_file.write_text(
            "class AuthService:\n    def login(self):\n        return True\n    def logout(self):\n        return False\n",
            encoding="utf-8"
        )

        changes = self.detector.detect_changes()
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, ChangeType.MODIFIED)
        self.assertEqual(changes[0].file_path, "src/auth.py")

        res = self.updater.apply_changes(self.state, changes, self.graph_manager)

        self.assertFalse(res.full_scan_fallback_triggered)
        self.assertEqual(res.re_extracted_symbols_count, 3)  # AuthService, login, logout

        symbol_names = [s.name for s in self.state.project_state.symbols]
        self.assertIn("AuthService", symbol_names)
        self.assertIn("AuthService.login", symbol_names)
        self.assertIn("AuthService.logout", symbol_names)
        self.assertIn("handle_login_route", symbol_names)  # api.py symbol preserved

    def test_file_deletion_cleanup_and_invalidation(self):
        """
        Deleting api.py should remove its symbols and mark its node STALE.
        """
        self.api_file.unlink()

        changes = self.detector.detect_changes()
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, ChangeType.DELETED)

        res = self.updater.apply_changes(self.state, changes, self.graph_manager)

        self.assertNotIn("src/api.py", self.state.project_state.files)
        symbol_names = [s.name for s in self.state.project_state.symbols]
        self.assertNotIn("handle_login_route", symbol_names)
        self.assertIn("api", res.invalidated_node_ids)

    def test_invalidation_propagation_to_dependents(self):
        """
        Modifying upstream 'auth.py' should propagate STALE status to downstream 'api'.
        """
        time.sleep(0.05)
        self.auth_file.write_text("class AuthService:\n    pass\n", encoding="utf-8")

        changes = self.detector.detect_changes()
        res = self.updater.apply_changes(self.state, changes, self.graph_manager)

        self.assertIn("auth", res.invalidated_node_ids)
        self.assertIn("api", res.propagated_stale_node_ids)
        self.assertEqual(self.state.graph_nodes["auth"].status, Status.STALE)
        self.assertEqual(self.state.graph_nodes["api"].status, Status.STALE)

    def test_massive_changes_triggers_fallback_full_scan(self):
        """
        When change batch exceeds MAX_CHANGES_BEFORE_FALLBACK_FULL_SCAN (50),
        the updater must declare full_scan_fallback_triggered=True.
        """
        synthetic_changes = [
            FileChangeEvent(file_path=f"src/file_{i}.py", change_type=ChangeType.MODIFIED)
            for i in range(60)
        ]
        res = self.updater.apply_changes(self.state, synthetic_changes)
        self.assertTrue(res.full_scan_fallback_triggered)


if __name__ == "__main__":
    unittest.main()
