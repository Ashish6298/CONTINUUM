"""
Project Continuum - Serve Command Implementation
=================================================
Milestone 28 - Phase 32: `continuum serve` CLI Subcommand Implementation.
Provides rich terminal startup banner, options handling, daemon controls,
browser launching, and live filesystem watcher integration.
"""

import argparse
import os
from pathlib import Path
import sys
import threading
import time
from typing import Optional
import webbrowser

from server.daemon import ContinuumHttpDaemon, DaemonServerStatus
from server.auth import SessionAuthManager
from watcher.detector import WorkspaceChangeDetector
from watcher.updater import IncrementalStateUpdater


def register_serve_subcommand(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Registers the `serve` command in the CLI subparser."""
    serve_parser = subparsers.add_parser(
        "serve",
        help="Launch embedded Local Web Control Dashboard and REST API daemon"
    )
    serve_parser.add_argument(
        "--path",
        default=".",
        help="Workspace root path (default: current working directory)"
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to bind the HTTP server on (default: 8765, auto-fallback enabled)"
    )
    serve_parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host interface to bind on (restricted strictly to 127.0.0.1 / localhost)"
    )
    serve_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically open default web browser on launch"
    )
    serve_parser.add_argument(
        "--watch",
        action="store_true",
        help="Enable live filesystem watcher for dynamic background state updates"
    )
    serve_parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop any active running daemon associated with the current workspace"
    )
    serve_parser.add_argument(
        "--status",
        action="store_true",
        help="Check if a daemon is actively running on this workspace and print connection details"
    )
    return serve_parser


def print_serve_banner(status: DaemonServerStatus, token: str, watch_enabled: bool) -> None:
    """Prints a styled terminal banner with server URL, token status, and hotkey hints."""
    if os.name == "nt":
        os.system("")

    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[32m"
    CYAN = "\033[36m"
    YELLOW = "\033[33m"
    GRAY = "\033[90m"
    MAGENTA = "\033[35m"

    banner = f"""
{BOLD}{MAGENTA}┌─ CONTINUUM WEB CONTROL DASHBOARD ──────────────────────────────────────────┐{RESET}
│                                                                            │
│  {GREEN}●{RESET} {BOLD}Dashboard URL  :{RESET} {CYAN}{status.server_url}{RESET}
│  {GRAY}📁 Workspace Root:{RESET} {status.workspace_root}
│  {YELLOW}🔑 Auth Token    :{RESET} {token if token else 'None'}
│  {GRAY}👁️  Live Watcher  :{RESET} {'Enabled' if watch_enabled else 'Disabled'}
│  {GRAY}⚙️  Process PID   :{RESET} {status.pid}
│                                                                            │
│  {BOLD}Shortcuts & Actions:{RESET}                                                     │
│    • Press {BOLD}Ctrl+C{RESET} to gracefully stop server daemon                        │
│    • Open in browser: {CYAN}{status.server_url}{RESET}                             │
│                                                                            │
{BOLD}{MAGENTA}└────────────────────────────────────────────────────────────────────────────┘{RESET}
"""
    try:
        if hasattr(sys.stdout, "buffer") and hasattr(sys.stdout.buffer, "write"):
            sys.stdout.buffer.write(banner.encode("utf-8"))
            sys.stdout.buffer.flush()
        else:
            print(banner)
    except Exception:
        print(banner)


def handle_serve(args: argparse.Namespace, sleep_func=time.sleep) -> int:
    """Handles execution of `continuum serve` CLI command."""
    workspace_root = Path(args.path).resolve()

    # 1. Handle --stop option
    if getattr(args, "stop", False):
        stopped = ContinuumHttpDaemon.stop_existing(str(workspace_root))
        if stopped:
            print(f"[OK] Stopped active Continuum daemon on workspace: {workspace_root}")
            return 0
        else:
            print(f"[INFO] No active Continuum daemon found running on workspace: {workspace_root}")
            return 0

    # 2. Handle --status option
    if getattr(args, "status", False):
        status = ContinuumHttpDaemon.get_saved_status(str(workspace_root))
        if status.is_running:
            auth_mgr = SessionAuthManager(workspace_root)
            token = auth_mgr.get_token() or "None"
            print(f"Continuum Daemon Status: RUNNING (PID: {status.pid})")
            print(f"  Server URL:     {status.server_url}")
            print(f"  Workspace Root: {status.workspace_root}")
            print(f"  Auth Token:     {token}")
            if status.started_at:
                print(f"  Started At:     {status.started_at}")
        else:
            print(f"Continuum Daemon Status: STOPPED (Workspace: {workspace_root})")
        return 0

    # 3. Validate host constraint
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8765)
    no_browser = getattr(args, "no_browser", False)
    watch = getattr(args, "watch", False)

    # 4. Initialize and start HTTP daemon
    try:
        daemon = ContinuumHttpDaemon(
            workspace_root=str(workspace_root),
            host=host,
            default_port=port,
            require_auth=True
        )
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    # Optional background watcher thread
    watcher_stop_event = threading.Event()
    watcher_thread = None

    if watch:
        def _watch_loop():
            detector = WorkspaceChangeDetector(str(workspace_root))
            updater = IncrementalStateUpdater(str(workspace_root))
            while not watcher_stop_event.is_set():
                try:
                    events = detector.detect_changes()
                    if events:
                        updater.apply_changes(events)
                except Exception:
                    pass
                time.sleep(1.0)

        watcher_thread = threading.Thread(target=_watch_loop, daemon=True)
        watcher_thread.start()

    try:
        # Start daemon in foreground/background
        status = daemon.start(run_in_background=True)
    except RuntimeError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        if watch and watcher_stop_event:
            watcher_stop_event.set()
        return 1

    token = daemon.auth_manager.get_token() or ""

    # Print rich startup banner
    print_serve_banner(status, token, watch)

    # Launch browser if not disabled
    if not no_browser and status.server_url:
        try:
            webbrowser.open(status.server_url)
        except Exception:
            pass

    # Foreground wait loop until interrupt
    try:
        while True:
            sleep_func(0.5)
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Stopping Continuum Web Server...")
    finally:
        if watcher_stop_event:
            watcher_stop_event.set()
        daemon.stop()
        print("[OK] Continuum Web Server stopped cleanly.")

    return 0
