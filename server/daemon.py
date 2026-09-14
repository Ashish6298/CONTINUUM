"""
Project Continuum - Local HTTP Daemon & Lifecycle Management
=============================================================
Milestone 25 - Phase 25: Local HTTP Daemon Architecture & Lifecycle Management.
Provides an embedded, zero-dependency HTTP server bound strictly to loopback interfaces,
supporting automatic port fallback, PID management, and clean lifecycle controls.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import socket
import socketserver
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple


@dataclass
class ServerConfig:
    """Configuration options for Continuum HTTP Daemon."""
    workspace_root: str
    host: str = "127.0.0.1"
    default_port: int = 8765
    max_port_attempts: int = 10
    poll_interval_seconds: float = 1.0


@dataclass
class DaemonServerStatus:
    """Runtime status for the Continuum HTTP Daemon."""
    is_running: bool
    pid: Optional[int] = None
    host: str = "127.0.0.1"
    port: Optional[int] = None
    server_url: Optional[str] = None
    workspace_root: str = ""
    started_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP Server with socket address reuse."""
    allow_reuse_address = True
    daemon_threads = True


class DefaultHealthHandler(BaseHTTPRequestHandler):
    """Minimal built-in HTTP request handler for Phase 25 lifecycle testing."""

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy standard HTTP access logs to keep stdout clean
        pass

    def do_GET(self) -> None:
        if self.path in ("/", "/api/status", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            payload = {
                "status": "online",
                "system": "Continuum HTTP Daemon",
                "version": "1.2.0-dev",
                "path": self.path,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Not Found"}).encode("utf-8"))


class ContinuumHttpDaemon:
    """
    Local HTTP server daemon managing port negotiation, PID lockfiles,
    and background/foreground server lifecycle for Continuum.
    """

    ALLOWED_LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}

    def __init__(
        self,
        workspace_root: str,
        host: str = "127.0.0.1",
        default_port: int = 8765,
        max_port_attempts: int = 10,
        handler_class: Callable[..., BaseHTTPRequestHandler] = DefaultHealthHandler
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.host = host
        self.default_port = default_port
        self.max_port_attempts = max_port_attempts
        self.handler_class = handler_class

        # Validate security constraint: strictly loopback only
        self._validate_host_security(self.host)

        self._continuum_dir = self.workspace_root / ".continuum"
        self._pid_file = self._continuum_dir / "daemon.pid"
        self._status_file = self._continuum_dir / "daemon_server.json"

        self._server: Optional[ThreadingHTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._bound_port: Optional[int] = None
        self._started_at: Optional[str] = None
        self._is_running = False

    @classmethod
    def _validate_host_security(cls, host: str) -> None:
        """Enforces that the host binding is strictly loopback to prevent exposure."""
        if host not in cls.ALLOWED_LOOPBACK_HOSTS:
            raise ValueError(
                f"Security Violation: Host '{host}' is not a permitted loopback address. "
                f"Continuum HTTP Daemon only binds to {cls.ALLOWED_LOOPBACK_HOSTS}."
            )

    def find_available_port(self) -> int:
        """Finds the first open port starting from default_port."""
        for port_candidate in range(self.default_port, self.default_port + self.max_port_attempts):
            if self._is_port_available(self.host, port_candidate):
                return port_candidate
        raise RuntimeError(
            f"Unable to bind HTTP server: all ports from {self.default_port} "
            f"to {self.default_port + self.max_port_attempts - 1} are currently in use."
        )

    @staticmethod
    def _is_port_available(host: str, port: int) -> bool:
        """Checks whether a port is free to bind on the host without false SO_REUSEADDR sharing."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if sys.platform != "win32":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            else:
                # On Windows, SO_EXCLUSIVEADDRUSE prevents stealing occupied ports
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind((host, port))
            return True
        except (OSError, socket.error):
            return False
        finally:
            s.close()

    def start(self, run_in_background: bool = True) -> DaemonServerStatus:
        """
        Starts the HTTP server daemon.
        Negotiates an available port, initializes PID lockfiles, and launches the server.
        """
        if self._is_running:
            return self.get_status()

        # Check existing PID file to avoid duplicate running daemons
        existing_pid = self._check_existing_daemon()
        if existing_pid:
            raise RuntimeError(
                f"Continuum HTTP Daemon is already running on workspace (PID: {existing_pid}). "
                f"Use stop() or terminate the existing process first."
            )

        self._continuum_dir.mkdir(parents=True, exist_ok=True)
        self._bound_port = self.find_available_port()

        # Instantiate HTTP Server
        self._server = ThreadingHTTPServer((self.host, self._bound_port), self.handler_class)
        self._is_running = True
        self._started_at = datetime.now(timezone.utc).isoformat()

        # Save PID file and status snapshot
        current_pid = os.getpid()
        self._pid_file.write_text(str(current_pid), encoding="utf-8")
        self._save_status_snapshot()

        if run_in_background:
            self._server_thread = threading.Thread(target=self._serve_loop, daemon=True)
            self._server_thread.start()
            # Brief yield to ensure socket listening starts
            time.sleep(0.05)
        else:
            self._serve_loop()

        return self.get_status()

    def _serve_loop(self) -> None:
        """Internal server loop."""
        try:
            if self._server:
                self._server.serve_forever(poll_interval=0.2)
        except Exception:
            pass
        finally:
            self._is_running = False

    def stop(self) -> DaemonServerStatus:
        """Gracefully shuts down the HTTP server and cleans up lockfiles."""
        self._is_running = False

        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None

        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=2.0)
            self._server_thread = None

        # Clean up lockfiles
        if self._pid_file.exists():
            try:
                self._pid_file.unlink()
            except OSError:
                pass

        if self._status_file.exists():
            try:
                self._status_file.unlink()
            except OSError:
                pass

        status = self.get_status()
        self._bound_port = None
        self._started_at = None
        return status

    def get_status(self) -> DaemonServerStatus:
        """Returns the current runtime status of the daemon."""
        pid = os.getpid() if self._is_running else None
        server_url = f"http://{self.host}:{self._bound_port}" if (self._is_running and self._bound_port) else None

        return DaemonServerStatus(
            is_running=self._is_running,
            pid=pid,
            host=self.host,
            port=self._bound_port,
            server_url=server_url,
            workspace_root=str(self.workspace_root),
            started_at=self._started_at
        )

    def _save_status_snapshot(self) -> None:
        """Persists the daemon runtime status to .continuum/daemon_server.json."""
        try:
            status = self.get_status()
            self._status_file.write_text(json.dumps(status.to_dict(), indent=2), encoding="utf-8")
        except OSError:
            pass

    def _check_existing_daemon(self) -> Optional[int]:
        """Checks if a daemon process recorded in .continuum/daemon.pid is actively alive."""
        if not self._pid_file.exists():
            return None
        try:
            content = self._pid_file.read_text(encoding="utf-8").strip()
            if not content:
                return None
            pid = int(content)

            # If it's our own current process, it's not a conflict
            if pid == os.getpid():
                return None

            # Verify if process is alive
            if self._is_pid_running(pid):
                return pid
            else:
                # Stale PID file, safe to remove
                self._pid_file.unlink(missing_ok=True)
                return None
        except Exception:
            return None

    @staticmethod
    def _is_pid_running(pid: int) -> bool:
        """Checks if a process ID is running on the operating system."""
        if pid <= 0:
            return False
        if sys.platform == "win32":
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return exit_code.value == STILL_ACTIVE
        else:
            try:
                os.kill(pid, 0)
                return True
            except (OSError, ProcessLookupError):
                return False
