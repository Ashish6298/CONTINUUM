"""
Project Continuum - Test `continuum serve` CLI Subcommand (Phase 32)
=====================================================================
Verifies:
1. `continuum serve` Command Registration:
   - CLI parser successfully recognizes `serve` subcommand.
   - All options (`--port`, `--host`, `--no-browser`, `--watch`, `--stop`, `--status`, `--path`) parsed properly.
2. Status Check (`continuum serve --status`):
   - Correctly reports STOPPED when daemon is offline.
   - Correctly reports RUNNING with PID, server URL, workspace, and token when daemon is online.
3. Stop Control (`continuum serve --stop`):
   - Successfully terminates running daemon and cleans up state lockfiles.
   - Handles stop request gracefully when no daemon is running.
4. Security & Loopback Constraint:
   - Rejects non-loopback host bindings with error status.
5. Watcher Integration:
   - Starts and cleanly shuts down background watcher thread when `--watch` is specified.
6. Browser Launch Suppression:
   - `--no-browser` suppresses browser launch.
"""

import io
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

from cli.main import main, build_parser
from cli.serve import handle_serve
from server.daemon import ContinuumHttpDaemon


class TestServeCliSubcommand(unittest.TestCase):
    """Test suite for Phase 32: `continuum serve` CLI Subcommand."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self.temp_dir.name)

        # Create basic files
        (self.workspace_root / "app.py").write_text("def hello(): pass\n", encoding="utf-8")

    def tearDown(self) -> None:
        ContinuumHttpDaemon.stop_existing(str(self.workspace_root))
        self.temp_dir.cleanup()

    def test_serve_subcommand_parser_options(self) -> None:
        """Verifies argument parsing for `serve` and all supported options."""
        parser = build_parser()
        args = parser.parse_args([
            "serve",
            "--path", str(self.workspace_root),
            "--port", "8999",
            "--host", "127.0.0.1",
            "--no-browser",
            "--watch"
        ])
        self.assertEqual(args.command, "serve")
        self.assertEqual(args.path, str(self.workspace_root))
        self.assertEqual(args.port, 8999)
        self.assertEqual(args.host, "127.0.0.1")
        self.assertTrue(args.no_browser)
        self.assertTrue(args.watch)
        self.assertFalse(args.stop)
        self.assertFalse(args.status)

    def test_serve_status_when_stopped(self) -> None:
        """Verifies `continuum serve --status` prints STOPPED when no daemon is active."""
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            exit_code = main(["serve", "--path", str(self.workspace_root), "--status"])
            self.assertEqual(exit_code, 0)
            output = mock_stdout.getvalue()
            self.assertIn("STOPPED", output)

    def test_serve_status_when_running_and_stop_command(self) -> None:
        """Verifies `continuum serve --status` and `continuum serve --stop` against a live daemon."""
        daemon = ContinuumHttpDaemon(
            workspace_root=str(self.workspace_root),
            host="127.0.0.1",
            default_port=9310,
            require_auth=True
        )
        daemon.start(run_in_background=True)
        try:
            # 1. Test status reporting
            with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                exit_code = main(["serve", "--path", str(self.workspace_root), "--status"])
                self.assertEqual(exit_code, 0)
                output = mock_stdout.getvalue()
                self.assertIn("RUNNING", output)
                self.assertIn("Server URL:", output)

            # 2. Test stop command
            with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                exit_code = main(["serve", "--path", str(self.workspace_root), "--stop"])
                self.assertEqual(exit_code, 0)
                output = mock_stdout.getvalue()
                self.assertIn("Stopped active Continuum daemon", output)

            # 3. Verify status is now STOPPED
            with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                exit_code = main(["serve", "--path", str(self.workspace_root), "--status"])
                self.assertEqual(exit_code, 0)
                output = mock_stdout.getvalue()
                self.assertIn("STOPPED", output)
        finally:
            daemon.stop()

    def test_serve_stop_when_not_running(self) -> None:
        """Verifies `continuum serve --stop` handles absence of daemon gracefully."""
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            exit_code = main(["serve", "--path", str(self.workspace_root), "--stop"])
            self.assertEqual(exit_code, 0)
            output = mock_stdout.getvalue()
            self.assertIn("No active Continuum daemon found", output)

    def test_serve_rejects_non_loopback_host(self) -> None:
        """Verifies security violation when passing a non-loopback host."""
        with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
            exit_code = main([
                "serve",
                "--path", str(self.workspace_root),
                "--host", "192.168.1.50"
            ])
            self.assertEqual(exit_code, 1)
            output = mock_stderr.getvalue()
            self.assertIn("Security Violation", output)

    @patch("webbrowser.open")
    def test_serve_startup_and_browser_suppression(self, mock_browser: MagicMock) -> None:
        """Verifies server start and that --no-browser suppresses browser launch."""
        parser = build_parser()
        args = parser.parse_args([
            "serve",
            "--path", str(self.workspace_root),
            "--port", "9320",
            "--no-browser"
        ])
        
        def mock_sleep_interrupt(secs):
            raise KeyboardInterrupt()

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            exit_code = handle_serve(args, sleep_func=mock_sleep_interrupt)
            self.assertEqual(exit_code, 0)
            mock_browser.assert_not_called()
            output = mock_stdout.getvalue()
            self.assertIn("CONTINUUM WEB CONTROL DASHBOARD", output)
            self.assertIn("Continuum Web Server stopped cleanly", output)

    @patch("webbrowser.open")
    def test_serve_startup_and_watcher_integration(self, mock_browser: MagicMock) -> None:
        """Verifies server start with --watch enables background observation."""
        parser = build_parser()
        args = parser.parse_args([
            "serve",
            "--path", str(self.workspace_root),
            "--port", "9330",
            "--watch",
            "--no-browser"
        ])

        def mock_sleep_interrupt(secs):
            raise KeyboardInterrupt()

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            exit_code = handle_serve(args, sleep_func=mock_sleep_interrupt)
            self.assertEqual(exit_code, 0)
            output = mock_stdout.getvalue()
            self.assertIn("Live Watcher", output)
            self.assertIn("Enabled", output)
            self.assertIn("Continuum Web Server stopped cleanly", output)


if __name__ == "__main__":
    unittest.main()
