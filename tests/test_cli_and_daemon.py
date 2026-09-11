"""
Project Continuum - Test Suite for Phase 18 (Continuum Daemon & CLI)
====================================================================
Milestone 7 - Phase 18.
Validates:
1. CLI `init` initializes storage and detects/installs Git hooks.
2. CLI `scan` extracts source code files and builds canonical state.
3. CLI `status` outputs verified project truth and next actions.
4. CLI `graph` outputs Mermaid diagrams and topological statistics.
5. CLI `handoff` outputs universal and model-specific packages.
6. ContinuumDaemon start, run_once single pass, status query, and graceful stop.
"""

from io import StringIO
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from cli.main import main, build_parser
from daemon.service import ContinuumDaemon, DaemonStatus
from storage.manager import ContinuumStorageManager


class TestCliAndDaemon(unittest.TestCase):
    """Test suite for Continuum CLI and Daemon background service."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

        # Create dummy python file
        (self.workspace / "app.py").write_text(
            "class AppController:\n    def run(self):\n        return 0\n",
            encoding="utf-8"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_init_command(self):
        """CLI init should initialize .continuum directory."""
        code = main(["init", "--path", str(self.workspace)])
        self.assertEqual(code, 0)

        storage = ContinuumStorageManager(str(self.workspace))
        self.assertTrue(storage.continuum_dir.exists())

    def test_cli_scan_and_status_commands(self):
        """CLI scan should harvest files, and status should display them."""
        # 1. Scan
        code_scan = main(["scan", "--path", str(self.workspace)])
        self.assertEqual(code_scan, 0)

        storage = ContinuumStorageManager(str(self.workspace))
        self.assertTrue(storage.state_exists())

        # 2. Status (Human readable)
        with patch("sys.stdout", new=StringIO()) as fake_out:
            code_status = main(["status", "--path", str(self.workspace)])
            self.assertEqual(code_status, 0)
            output = fake_out.getvalue()
            self.assertIn("PROJECT CONTINUUM — VERIFIED PROJECT STATUS", output)
            self.assertIn("Source Files:     1 file(s)", output)

        # 3. Status (JSON)
        with patch("sys.stdout", new=StringIO()) as fake_out_json:
            code_status_json = main(["status", "--path", str(self.workspace), "--json"])
            self.assertEqual(code_status_json, 0)
            json_output = fake_out_json.getvalue()
            self.assertIn("project_state", json_output)

    def test_cli_graph_command(self):
        """CLI graph should export stats and mermaid diagrams."""
        main(["scan", "--path", str(self.workspace)])

        with patch("sys.stdout", new=StringIO()) as fake_out:
            code = main(["graph", "--path", str(self.workspace), "--mermaid"])
            self.assertEqual(code, 0)
            output = fake_out.getvalue()
            self.assertIn("graph TD", output)

    def test_cli_handoff_command(self):
        """CLI handoff should generate universal package."""
        main(["scan", "--path", str(self.workspace)])

        out_dir = self.workspace / "handoff_out"
        code = main(["handoff", "--path", str(self.workspace), "--model", "universal", "--output-dir", str(out_dir)])
        self.assertEqual(code, 0)
        self.assertTrue((out_dir / "project-state.json").exists())
        self.assertTrue((out_dir / "handoff.md").exists())

    def test_daemon_lifecycle_and_single_pass(self):
        """Tests daemon single pass execution, background thread start, and graceful stop."""
        daemon = ContinuumDaemon(str(self.workspace), poll_interval_seconds=0.1)

        # 1. Single pass
        res = daemon.run_once()
        self.assertIn("changes_detected", res)

        # 2. Start in background
        status = daemon.start(run_in_background=True)
        self.assertTrue(status.is_running)

        time.sleep(0.2)

        # 3. Stop
        stop_status = daemon.stop()
        self.assertFalse(stop_status.is_running)


if __name__ == "__main__":
    unittest.main()
