"""
Project Continuum - Daemon Service & Workspace Observer
========================================================
Milestone 7 - Phase 18: Continuum Daemon & CLI.
Implements the continuous background monitoring service that synchronizes
workspace changes into persistent Canonical State.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Dict, Optional

from core.serializer import CanonicalStateSerializer
from core.state_models import CanonicalProjectState
from storage.manager import ContinuumStorageManager
from storage.recovery import StateRecoveryManager
from watcher.detector import WorkspaceChangeDetector
from watcher.updater import IncrementalStateUpdater
from graph.manager import StateGraphManager


@dataclass
class DaemonStatus:
    is_running: bool
    pid: Optional[int] = None
    workspace_root: str = ""
    started_at: Optional[str] = None
    last_tick_at: Optional[str] = None
    cycles_completed: int = 0
    total_changes_processed: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ContinuumDaemon:
    """
    Background daemon service monitoring workspace filesystem events,
    applying incremental state updates, and persisting to .continuum/.
    """

    def __init__(
        self,
        workspace_root: str,
        poll_interval_seconds: float = 1.0
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.poll_interval = poll_interval_seconds
        self._storage = ContinuumStorageManager(str(self.workspace_root))
        self._recovery = StateRecoveryManager(self._storage)
        self._detector = WorkspaceChangeDetector(str(self.workspace_root))
        self._updater = IncrementalStateUpdater(str(self.workspace_root))

        self._pid_file = self._storage.continuum_dir / "daemon.pid"
        self._status_file = self._storage.continuum_dir / "daemon.json"
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._cycles = 0
        self._total_changes = 0
        self._started_at: Optional[str] = None

    def start(self, run_in_background: bool = False) -> DaemonStatus:
        """Starts daemon monitoring loop."""
        self._storage.initialize_storage()
        self._detector.initialize_baseline()
        self._stop_event.clear()
        self._started_at = datetime.now(timezone.utc).isoformat()

        # Write PID file
        self._pid_file.write_text(str(os.getpid()), encoding="utf-8")

        if run_in_background:
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
        else:
            self._run_loop()

        return self.get_status()

    def stop(self) -> DaemonStatus:
        """Stops the daemon gracefully."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

        if self._pid_file.exists():
            try:
                self._pid_file.unlink()
            except OSError:
                pass

        return self.get_status()

    def run_once(self) -> Dict[str, Any]:
        """
        Executes a single check and synchronization cycle.
        """
        self._storage.initialize_storage()

        # Load or initialize state
        if self._storage.state_exists():
            try:
                state = self._storage.load_state(validate=True)
            except Exception:
                rec_res = self._recovery.recover_corrupted_state()
                if rec_res.success:
                    state = self._storage.load_state(validate=True)
                else:
                    state = CanonicalProjectState(project_id="proj_auto_init")
        else:
            state = CanonicalProjectState(project_id="proj_auto_init")

        # Detect changes
        changes = self._detector.detect_changes()
        result_info = {"changes_detected": len(changes), "updated": False}

        if changes:
            graph_manager = StateGraphManager(state)
            update_res = self._updater.apply_changes(state, changes, graph_manager)
            self._storage.save_state(state, create_history_snapshot=True)
            self._total_changes += len(changes)
            result_info["updated"] = True
            result_info["details"] = update_res.to_dict()

        self._cycles += 1
        self._write_status_file()
        return result_info

    def get_status(self) -> DaemonStatus:
        """Returns current daemon operational status."""
        is_running = not self._stop_event.is_set() and (self._thread.is_alive() if self._thread else False)
        pid = None
        if self._pid_file.exists():
            try:
                pid = int(self._pid_file.read_text().strip())
            except Exception:
                pass

        return DaemonStatus(
            is_running=is_running,
            pid=pid,
            workspace_root=str(self.workspace_root),
            started_at=self._started_at,
            last_tick_at=datetime.now(timezone.utc).isoformat(),
            cycles_completed=self._cycles,
            total_changes_processed=self._total_changes
        )

    def _run_loop(self) -> None:
        """Internal worker loop."""
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                pass
            time.sleep(self.poll_interval)

    def _write_status_file(self) -> None:
        """Persists daemon heartbeat to .continuum/daemon.json."""
        status = self.get_status()
        try:
            self._status_file.write_text(json.dumps(status.to_dict(), indent=2), encoding="utf-8")
        except Exception:
            pass
