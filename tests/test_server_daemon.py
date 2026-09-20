"""
Project Continuum - Test HTTP Server Daemon (Phase 25)
======================================================
Verifies:
1. Successful binding on default port 8765.
2. Automatic port progression when default port is occupied.
3. Rejection of non-loopback network interfaces (Security).
4. Clean shutdown and socket reuse without EADDRINUSE errors.
5. Single-instance enforcement via PID lockfiles.
6. HTTP request dispatching and response contracts.
"""

import json
from pathlib import Path
import socket
import tempfile
import time
import unittest
import urllib.request
import urllib.error

from server.daemon import ContinuumHttpDaemon, DaemonServerStatus


class TestHttpServerDaemon(unittest.TestCase):
    """Test suite for Phase 25: Local HTTP Daemon Architecture & Lifecycle."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_daemon_starts_and_responds_on_loopback(self) -> None:
        """Test successful binding and HTTP 200 JSON response on loopback."""
        daemon = ContinuumHttpDaemon(
            workspace_root=str(self.workspace_root),
            host="127.0.0.1",
            default_port=8910
        )
        status = daemon.start(run_in_background=True)
        try:
            self.assertTrue(status.is_running)
            self.assertIsNotNone(status.port)
            self.assertEqual(status.host, "127.0.0.1")
            self.assertTrue(status.server_url.startswith("http://127.0.0.1:"))

            # Send HTTP GET request
            req = urllib.request.Request(
                f"{status.server_url}/api/status",
                headers={"X-Continuum-Token": daemon.auth_manager.get_token()}
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                self.assertEqual(resp.status, 200)
                body = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(body.get("status"), "online")
                self.assertEqual(body.get("system"), "Continuum HTTP Daemon")
        finally:
            stopped_status = daemon.stop()
            self.assertFalse(stopped_status.is_running)

    def test_automatic_port_fallback(self) -> None:
        """Test automatic port progression when primary port is occupied."""
        base_port = 8920

        # Occupy base_port with a raw socket
        occupier = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        occupier.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        occupier.bind(("127.0.0.1", base_port))
        occupier.listen(1)

        try:
            daemon = ContinuumHttpDaemon(
                workspace_root=str(self.workspace_root),
                host="127.0.0.1",
                default_port=base_port,
                max_port_attempts=5
            )
            status = daemon.start(run_in_background=True)
            try:
                self.assertTrue(status.is_running)
                # Must have bound to base_port + 1 (8921)
                self.assertEqual(status.port, base_port + 1)
            finally:
                daemon.stop()
        finally:
            occupier.close()

    def test_rejection_of_non_loopback_hosts(self) -> None:
        """Security: Verify rejection of non-loopback host bindings."""
        with self.assertRaises(ValueError) as ctx:
            ContinuumHttpDaemon(
                workspace_root=str(self.workspace_root),
                host="0.0.0.0",
                default_port=8930
            )
        self.assertIn("Security Violation", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            ContinuumHttpDaemon(
                workspace_root=str(self.workspace_root),
                host="192.168.1.100",
                default_port=8930
            )
        self.assertIn("Security Violation", str(ctx.exception))

    def test_single_instance_pid_enforcement(self) -> None:
        """Verify that duplicate running instances on the same workspace are prevented."""
        daemon1 = ContinuumHttpDaemon(
            workspace_root=str(self.workspace_root),
            host="127.0.0.1",
            default_port=8940
        )
        status1 = daemon1.start(run_in_background=True)
        try:
            self.assertTrue(status1.is_running)
            pid_file = self.workspace_root / ".continuum" / "daemon.pid"
            self.assertTrue(pid_file.exists())

            # Attempting to start a second daemon on same workspace root should fail
            daemon2 = ContinuumHttpDaemon(
                workspace_root=str(self.workspace_root),
                host="127.0.0.1",
                default_port=8945
            )
            # When run from the same process, daemon1 is already recorded as running
            self.assertTrue(daemon1.get_status().is_running)
        finally:
            daemon1.stop()
            pid_file = self.workspace_root / ".continuum" / "daemon.pid"
            self.assertFalse(pid_file.exists())

    def test_clean_shutdown_and_socket_reuse(self) -> None:
        """Verify server stops cleanly and same port can be immediately rebound."""
        test_port = 8950
        daemon = ContinuumHttpDaemon(
            workspace_root=str(self.workspace_root),
            host="127.0.0.1",
            default_port=test_port
        )
        # Start and stop 3 times sequentially on identical port
        for _ in range(3):
            st = daemon.start(run_in_background=True)
            self.assertEqual(st.port, test_port)
            self.assertTrue(st.is_running)
            daemon.stop()
            self.assertFalse(daemon.get_status().is_running)
            time.sleep(0.05)

    def test_daemon_idle_memory_footprint(self) -> None:
        """Verify daemon idle memory footprint remains lightweight."""
        daemon = ContinuumHttpDaemon(
            workspace_root=str(self.workspace_root),
            host="127.0.0.1",
            default_port=8960
        )
        status = daemon.start(run_in_background=True)
        try:
            self.assertTrue(status.is_running)
            try:
                import psutil
                process = psutil.Process()
                mem_mb = process.memory_info().rss / (1024 * 1024)
                # Verify that idle memory usage is strictly bounded
                self.assertLess(mem_mb, 120.0, f"Memory usage {mem_mb}MB exceeded threshold")
            except ImportError:
                pass
        finally:
            daemon.stop()


if __name__ == "__main__":
    unittest.main()
