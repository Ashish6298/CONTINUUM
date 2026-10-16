"""
Project Continuum - Phase 50 Verification Test Suite
===================================================
Milestone 35: Repository Discovery and Baseline
Phase 50: Repository and Architecture Inventory

Automated verification of architectural inventory, package boundaries,
entry points, dependency minimalism, storage locations, and existing concepts.
"""

import inspect
import json
from pathlib import Path
import sys
import unittest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestPhase50ArchitectureInventory(unittest.TestCase):
    """Verifies all structural findings from Phase 50 inventory."""

    def test_package_structure_and_imports(self):
        """Verify all core packages and architectural modules are importable."""
        modules = [
            "core.enums",
            "core.state_models",
            "core.schema",
            "core.serializer",
            "storage.manager",
            "storage.models",
            "storage.recovery",
            "storage.hooks",
            "graph.manager",
            "graph.query",
            "graph.propagator",
            "handoff.packager",
            "handoff.adapters",
            "server.routes",
            "server.auth",
            "server.sanitizer",
            "server.static_manager",
            "cli.main",
            "context.selector",
            "context.pruner",
            "extractors.workspace_extractor",
            "extractors.git_extractor",
            "extractors.config_extractor",
            "daemon.service",
            "watcher.detector"
        ]
        for mod_name in modules:
            __import__(mod_name)
            self.assertIn(mod_name, sys.modules, f"Module {mod_name} should be loaded in sys.modules")

    def test_zero_production_dependencies(self):
        """Verify pyproject.toml defines zero third-party production dependencies."""
        pyproject_path = _PROJECT_ROOT / "pyproject.toml"
        self.assertTrue(pyproject_path.exists(), "pyproject.toml must exist")
        content = pyproject_path.read_text(encoding="utf-8")
        
        # Check dependencies list is empty
        self.assertIn("dependencies = []", content, "Project Continuum must maintain zero third-party production dependencies")
        self.assertIn("continuum-toolkit", content)

    def test_cli_subcommands_registration(self):
        """Verify all documented CLI subcommands exist in the parser."""
        from cli.main import build_parser
        parser = build_parser()
        
        # Extract registered subcommand names from subparsers action
        subcommand_choices = set()
        for action in parser._actions:
            if type(action).__name__ == "_SubParsersAction" and action.choices:
                subcommand_choices.update(action.choices.keys())
                
        expected_commands = {
            "init", "status", "scan", "graph", "handoff", 
            "daemon", "serve", "launch", "bookmarklet", "browser", "setup"
        }
        for cmd in expected_commands:
            self.assertIn(cmd, subcommand_choices, f"CLI subcommand '{cmd}' must be registered")

    def test_existing_checkpoint_and_lineage_concept(self):
        """Verify existing HandoffCheckpoint and lineage mechanisms in core/state_models."""
        from core.state_models import HandoffCheckpoint, HandoffCheckpointManager
        
        # Verify checkpoint fields exist
        fields = inspect.signature(HandoffCheckpoint).parameters
        expected_fields = [
            "checkpoint_id", "origin_model", "target_model", "timestamp",
            "prompt_summary", "compressed_prompt", "total_messages",
            "total_code_blocks", "parent_checkpoint_id", "metadata"
        ]
        for f in expected_fields:
            self.assertIn(f, fields, f"Field '{f}' must exist on HandoffCheckpoint")

        # Verify lineage traversal method
        self.assertTrue(
            hasattr(HandoffCheckpointManager, "get_lineage"),
            "HandoffCheckpointManager must provide get_lineage method"
        )

    def test_storage_manager_contracts(self):
        """Verify ContinuumStorageManager adheres to durability and snapshot contracts."""
        from storage.manager import ContinuumStorageManager
        methods = ["initialize_storage", "save_state", "load_state", "state_exists", "get_metadata"]
        for m in methods:
            self.assertTrue(
                hasattr(ContinuumStorageManager, m),
                f"ContinuumStorageManager must implement '{m}'"
            )

    def test_server_routes_and_security_guards(self):
        """Verify ContinuumApiHandler contains expected endpoints and security guards."""
        from server.routes import ContinuumApiHandler
        from server.auth import CorsOriginGuard, SessionAuthManager
        from server.sanitizer import DaemonSanitizer
        
        self.assertTrue(hasattr(ContinuumApiHandler, "handle_get_checkpoints"))
        self.assertTrue(hasattr(ContinuumApiHandler, "handle_post_checkpoint"))
        self.assertTrue(hasattr(ContinuumApiHandler, "handle_post_workspace_sync"))
        self.assertTrue(hasattr(CorsOriginGuard, "is_origin_allowed"))
        self.assertTrue(hasattr(DaemonSanitizer, "sanitize_text"))

    def test_static_assets_exist(self):
        """Verify Web Dashboard static assets exist and are non-empty."""
        static_dir = _PROJECT_ROOT / "server" / "static"
        expected_files = ["index.html", "dashboard.css", "dashboard.js"]
        for fname in expected_files:
            fpath = static_dir / fname
            self.assertTrue(fpath.is_file(), f"Static asset {fname} must exist")
            self.assertGreater(fpath.stat().st_size, 0, f"Static asset {fname} must not be empty")

    def test_github_workflows_exist(self):
        """Verify CI/CD workflows are present in .github/workflows/."""
        wf_dir = _PROJECT_ROOT / ".github" / "workflows"
        self.assertTrue((wf_dir / "ci.yml").is_file(), "ci.yml must exist")
        self.assertTrue((wf_dir / "release.yml").is_file(), "release.yml must exist")


if __name__ == "__main__":
    unittest.main()
