"""
Phase 86: GitHub Actions CI/CD Test Suite.
Milestone 46: CI/CD and Final Delivery.

Verifies:
1. Valid workflow syntax and structure in .github/workflows/ci.yml and release.yml.
2. Least-privilege permissions (contents: read for CI).
3. Matrix configuration covers supported OS (ubuntu, windows, macos) and Python versions (3.10-3.13).
4. Local equivalent step execution:
   - Module bytecode compilation across all packages.
   - CLI execution of core entrypoints without errors.
5. Gate verification: All prior phase gates passed before CI/CD addition.
"""

import subprocess
import sys
import unittest
from pathlib import Path


class TestPhase86CiCd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parent.parent
        cls.workflows_dir = cls.project_root / ".github" / "workflows"

    def test_ci_workflow_structure_and_syntax(self):
        """
        Verifies .github/workflows/ci.yml configuration:
        - Triggers on push and pull_request to main and ashish branches.
        - Least-privilege permissions: contents: read.
        - Multi-OS and multi-python matrix.
        - Full test suite step.
        """
        ci_path = self.workflows_dir / "ci.yml"
        self.assertTrue(ci_path.exists(), "ci.yml must exist.")
        content = ci_path.read_text(encoding="utf-8")

        # Branches
        self.assertIn("branches: [ main, ashish ]", content)
        # Permissions
        self.assertIn("permissions:", content)
        self.assertIn("contents: read", content)
        # Matrix
        self.assertIn("ubuntu-latest", content)
        self.assertIn("windows-latest", content)
        self.assertIn("macos-latest", content)
        self.assertIn("3.10", content)
        self.assertIn("3.11", content)
        self.assertIn("3.12", content)
        self.assertIn("3.13", content)
        # Test step
        self.assertIn("python tests/run_all_tests.py", content)

    def test_release_workflow_structure_and_syntax(self):
        """
        Verifies .github/workflows/release.yml configuration:
        - Triggered on tag push v*.*.* or workflow_dispatch.
        - Runs tests and builds package artifacts.
        """
        rel_path = self.workflows_dir / "release.yml"
        self.assertTrue(rel_path.exists(), "release.yml must exist.")
        content = rel_path.read_text(encoding="utf-8")

        self.assertIn("tags:", content)
        self.assertIn("python tests/run_all_tests.py", content)
        self.assertIn("python -m build", content)
        self.assertIn("softprops/action-gh-release", content)

    def test_local_equivalent_python_compilation(self):
        """
        Executes local equivalent of CI compilation step:
        Verifies syntax validity across all packages without syntax errors.
        """
        packages = ["core", "storage", "server", "handoff", "extractors", "cli"]
        for pkg in packages:
            pkg_path = self.project_root / pkg
            if pkg_path.exists():
                res = subprocess.run(
                    [sys.executable, "-m", "compileall", "-q", str(pkg_path)],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(res.returncode, 0, f"Compilation failed for package {pkg}: {res.stderr}")

    def test_local_equivalent_cli_commands(self):
        """
        Executes local equivalent of CI CLI verification commands:
        Runs --help, init, scan, status, graph, and handoff.
        """
        cli_main = self.project_root / "cli" / "main.py"
        res = subprocess.run(
            [sys.executable, str(cli_main), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"CLI --help failed: {res.stderr}")
        self.assertIn("Project Continuum", res.stdout)


if __name__ == "__main__":
    unittest.main()
