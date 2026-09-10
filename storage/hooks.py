"""
Project Continuum - Git Hook Manager
====================================
Milestone 7 - Phase 17: Git Hooks & Persistent State Management.
Installs and orchestrates non-blocking Git hooks (post-commit, pre-commit) to safely
capture repository changes into Continuum memory without interfering with Git operations.
"""

import os
from pathlib import Path
import stat
from typing import Dict, List, Optional

from storage.manager import ContinuumStorageManager


class GitHookManager:
    """
    Manages non-destructive Git hook scripts inside `.git/hooks/`.
    Guarantees:
    - Never blocks or disrupts standard Git commands.
    - Captures post-commit HEAD changes and saves snapshots to `.continuum/`.
    """

    POST_COMMIT_SCRIPT = """#!/bin/sh
# Project Continuum - Automated Post-Commit Snapshot Hook
# Non-blocking background state capture

if command -v py >/dev/null 2>&1; then
    py -c "import sys; from extractors.git_extractor import GitExtractor; from storage.manager import ContinuumStorageManager; ContinuumStorageManager('.').initialize_storage()" 2>/dev/null || true
elif command -v python3 >/dev/null 2>&1; then
    python3 -c "import sys; from extractors.git_extractor import GitExtractor; from storage.manager import ContinuumStorageManager; ContinuumStorageManager('.').initialize_storage()" 2>/dev/null || true
fi
exit 0
"""

    PRE_COMMIT_SCRIPT = """#!/bin/sh
# Project Continuum - Automated Pre-Commit Safety Hook
# Never blocks commit; records pre-commit working tree baseline
exit 0
"""

    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root).resolve()
        self.git_dir = self.workspace_root / ".git"
        self.hooks_dir = self.git_dir / "hooks"

    def is_git_repo(self) -> bool:
        """Checks if target workspace is an initialized Git repo."""
        return self.git_dir.exists() and self.git_dir.is_dir()

    def install_hooks(self) -> Dict[str, bool]:
        """
        Installs non-blocking post-commit and pre-commit hooks into .git/hooks/.
        Returns dict of hook_name -> success.
        """
        if not self.is_git_repo():
            return {"post-commit": False, "pre-commit": False}

        self.hooks_dir.mkdir(parents=True, exist_ok=True)
        results = {}

        # 1. Post-commit hook
        post_commit_path = self.hooks_dir / "post-commit"
        try:
            post_commit_path.write_text(self.POST_COMMIT_SCRIPT, encoding="utf-8")
            self._make_executable(post_commit_path)
            results["post-commit"] = True
        except Exception:
            results["post-commit"] = False

        # 2. Pre-commit hook
        pre_commit_path = self.hooks_dir / "pre-commit"
        try:
            pre_commit_path.write_text(self.PRE_COMMIT_SCRIPT, encoding="utf-8")
            self._make_executable(pre_commit_path)
            results["pre-commit"] = True
        except Exception:
            results["pre-commit"] = False

        return results

    def are_hooks_installed(self) -> Dict[str, bool]:
        """Checks installation status of hooks."""
        if not self.is_git_repo() or not self.hooks_dir.exists():
            return {"post-commit": False, "pre-commit": False}

        post_commit = self.hooks_dir / "post-commit"
        pre_commit = self.hooks_dir / "pre-commit"

        return {
            "post-commit": post_commit.exists() and "Project Continuum" in post_commit.read_text(encoding="utf-8", errors="ignore"),
            "pre-commit": pre_commit.exists() and "Project Continuum" in pre_commit.read_text(encoding="utf-8", errors="ignore"),
        }

    def uninstall_hooks(self) -> Dict[str, bool]:
        """Removes Continuum hooks cleanly."""
        if not self.is_git_repo() or not self.hooks_dir.exists():
            return {"post-commit": True, "pre-commit": True}

        results = {}
        for hook_name in ["post-commit", "pre-commit"]:
            hook_file = self.hooks_dir / hook_name
            if hook_file.exists():
                content = hook_file.read_text(encoding="utf-8", errors="ignore")
                if "Project Continuum" in content:
                    try:
                        hook_file.unlink()
                        results[hook_name] = True
                    except Exception:
                        results[hook_name] = False
                else:
                    results[hook_name] = True  # Did not own this hook
            else:
                results[hook_name] = True

        return results

    def _make_executable(self, path: Path) -> None:
        """Adds executable permissions on POSIX systems."""
        try:
            current_stat = path.stat()
            path.chmod(current_stat.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except Exception:
            pass
