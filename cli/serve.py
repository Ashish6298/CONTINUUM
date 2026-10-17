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

    import re

    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[32m"
    CYAN = "\033[36m"
    YELLOW = "\033[33m"
    GRAY = "\033[90m"
    MAGENTA = "\033[35m"

    authenticated_url = f"{status.server_url}?token={token}" if token else status.server_url

    def vis_len(s: str) -> int:
        clean = re.sub(r"\033\[[0-9;]*m", "", s)
        return len(clean)

    def build_box(title: str, lines: list, color_code: str, box_width: int) -> str:
        title_width = vis_len(title)
        dashes_top = box_width - title_width - 5
        top = f"{BOLD}{color_code}┌─ {title} " + ("─" * max(0, dashes_top)) + f"┐{RESET}"
        bottom = f"{BOLD}{color_code}└" + ("─" * (box_width - 2)) + f"┘{RESET}"

        rows = [top]
        for line in lines:
            if line == "":
                rows.append(f"{BOLD}{color_code}│{RESET}" + (" " * (box_width - 2)) + f"{BOLD}{color_code}│{RESET}")
                continue
            if line == "---":
                rows.append(f"{BOLD}{color_code}├" + ("─" * (box_width - 2)) + f"┤{RESET}")
                continue

            v_width = vis_len(line)
            pad = box_width - v_width - 4
            if pad < 0:
                line = line[: box_width - 7] + "..."
                pad = 0
            rows.append(f"{BOLD}{color_code}│{RESET}  {line}" + (" " * pad) + f"{BOLD}{color_code}│{RESET}")

        rows.append(bottom)
        return "\n".join(rows)

    b1 = [
        "",
        f"{GREEN}[*] ACTIVE{RESET}  {BOLD}Dashboard URL  :{RESET} {CYAN}{status.server_url}{RESET}",
        f"{GRAY}[-] ROOT{RESET}    {BOLD}Workspace Path :{RESET} {status.workspace_root}",
        f"{YELLOW}[-] TOKEN{RESET}   {BOLD}Auth Token     :{RESET} {token if token else 'None'}",
        f"{CYAN}[-] WATCH{RESET}   {BOLD}Live Watcher   :{RESET} {'Enabled (Sub-millisecond AST Tracker)' if watch_enabled else 'Disabled'}",
        f"{GRAY}[-] PID{RESET}     {BOLD}Process PID    :{RESET} {status.pid}",
        "",
        f"{BOLD}Direct Instant-Access Link:{RESET}",
        f"{CYAN}{authenticated_url}{RESET}",
        "",
    ]

    b2 = [
        "",
        f"{CYAN}[01] LAUNCH & ENTER{RESET}",
        "     Browser opens automatically, or navigate via the Direct Link above.",
        "",
        f"{CYAN}[02] WORKSTREAM PARTITIONING{RESET}",
        "     Select an activity in the left dock or create a new session (Coding,",
        "     Study, Agent, Task) to keep deep context tracks strictly isolated.",
        "",
        f"{CYAN}[03] DURABLE CHECKPOINT CAPTURE{RESET}",
        f"     Click {MAGENTA}'Capture Checkpoint'{RESET} as milestones complete. Snapshots active",
        "     focus, finished tasks, and next actions durably to SQLite & JSON.",
        "",
        f"{CYAN}[04] DETERMINISTIC RESUME ENGINE{RESET}",
        "     Continuum auto-synthesizes a 6-point Resume Brief. Zero hallucination.",
        f"     Click {GREEN}'Copy Brief'{RESET} to immediately resume work where you left off.",
        "",
        f"{CYAN}[05] OMNI-MODEL AGENT HANDOFF{RESET}",
        f"     Click {MAGENTA}'Export Handoff'{RESET} to package prompt context bundles tailored with",
        "     token budgeting for Claude (200k), GPT-4o (128k), or Gemini (1M).",
        "",
        f"{CYAN}[06] TIME-TRAVEL & ISOLATED FORKING{RESET}",
        f"     Click {CYAN}'Inspect'{RESET} on any historical checkpoint to view read-only state.",
        f"     Click {GREEN}'Branch'{RESET} to fork an independent branch without mutating history.",
        "",
        f"{CYAN}[07] LOCAL FTS5 COGNITIVE SEARCH{RESET}",
        f"     Press {YELLOW}Alt+S{RESET} or click {CYAN}'Search'{RESET} for sub-millisecond full-text retrieval",
        "     across activities, decisions, and checkpoints -- 100% offline.",
        "",
        "---",
        f"{BOLD}Control Keybindings & Daemon Management:{RESET}",
        f"  * {YELLOW}Alt+S{RESET}   : Global FTS5 Search        * {YELLOW}Ctrl+C{RESET} : Graceful Server Stop",
        f"  * Background Stop Command   : {CYAN}continuum serve --stop{RESET}",
        "",
    ]

    # Calculate unified dynamic width so all boxes close cleanly
    max_len = max([vis_len(l) for l in b1 + b2 if l not in ("", "---")] + [vis_len("UNIVERSAL RESUME ANYWHERE // OPERATIONAL PROTOCOL") + 5, 84])
    unified_width = max_len + 4

    box1_str = build_box("CONTINUUM WEB CONTROL DASHBOARD", b1, MAGENTA, unified_width)
    box2_str = build_box("UNIVERSAL RESUME ANYWHERE // OPERATIONAL PROTOCOL", b2, CYAN, unified_width)

    banner = "\n" + box1_str + "\n\n" + box2_str + "\n"

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

    # Launch browser if not disabled - open with token in URL for auto-auth
    if not no_browser and status.server_url:
        try:
            browser_url = f"{status.server_url}?token={token}" if token else status.server_url
            webbrowser.open(browser_url)
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
