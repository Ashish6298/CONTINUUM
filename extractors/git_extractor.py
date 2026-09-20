"""
Project Continuum - Git History & Workspace Delta Evidence Extractor
====================================================================
Milestone 2 - Phase 3: Git History & Delta Analysis.
Extracts branch, HEAD commit, staged/unstaged changes, untracked files,
commit logs, and file churn metrics. Gracefully handles non-git folders
and repositories with zero commits without failing.
"""

from collections import defaultdict
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from core.enums import EvidenceType, EvidenceLevel
from core.evidence import Evidence
from core.state_models import (
    CanonicalProjectState,
    GitState,
    ProjectState,
)
from extractors.base import BaseEvidenceExtractor


class GitEvidenceExtractor(BaseEvidenceExtractor):
    """
    Extractor responsible for harvesting verifiable Git state and history.
    """

    @property
    def extractor_name(self) -> str:
        return "GitEvidenceExtractor"

    @property
    def supported_evidence_types(self) -> List[EvidenceType]:
        return [
            EvidenceType.GIT_STATUS,
            EvidenceType.GIT_DIFF,
            EvidenceType.GIT_COMMIT,
        ]

    def can_extract(self, target_path_or_input: str) -> bool:
        path = Path(target_path_or_input)
        return path.exists() and path.is_dir()

    def _run_git_command(self, repo_dir: Path, args: List[str]) -> Tuple[int, str, str]:
        """Runs a git command safely and returns (exit_code, stdout, stderr)."""
        try:
            res = subprocess.run(
                ["git"] + args,
                cwd=str(repo_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15
            )
            return res.returncode, res.stdout, res.stderr
        except Exception as e:
            return 1, "", str(e)

    def is_git_repository(self, root_path: Path) -> bool:
        """Checks if the given directory is within a valid git repository."""
        code, out, _ = self._run_git_command(root_path, ["rev-parse", "--is-inside-work-tree"])
        return code == 0 and out.strip() == "true"

    def get_head_info(self, root_path: Path) -> Tuple[Optional[str], Optional[str]]:
        """
        Extracts (branch_name, head_commit_sha).
        Handles unborn branches (repos with 0 commits).
        """
        # Get branch
        code, branch_out, _ = self._run_git_command(root_path, ["branch", "--show-current"])
        branch = branch_out.strip() if (code == 0 and branch_out.strip()) else None

        if not branch:
            # Fallback for older git or detached head
            code, sym_out, _ = self._run_git_command(root_path, ["symbolic-ref", "--short", "HEAD"])
            branch = sym_out.strip() if code == 0 and sym_out.strip() else "HEAD (detached)"

        # Get HEAD commit
        code, commit_out, _ = self._run_git_command(root_path, ["rev-parse", "HEAD"])
        cleaned_commit = commit_out.strip()
        head_commit = cleaned_commit if (code == 0 and len(cleaned_commit) == 40) else None

        return branch, head_commit

    def get_working_tree_status(self, root_path: Path) -> Dict[str, Any]:
        """
        Parses `git status --porcelain=v1` into staged, unstaged, untracked, and deleted files.
        """
        code, out, _ = self._run_git_command(root_path, ["status", "--porcelain=v1"])
        if code != 0:
            return {
                "is_dirty": False,
                "staged_files": [],
                "unstaged_files": [],
                "untracked_files": [],
                "deleted_files": []
            }

        staged: List[str] = []
        unstaged: List[str] = []
        untracked: List[str] = []
        deleted: List[str] = []

        for raw_line in out.splitlines():
            if not raw_line or len(raw_line) < 3:
                continue

            # In porcelain v1, the first 2 characters are status codes, followed by a space
            status_code = raw_line[:2]
            file_path = raw_line[3:].strip()
            # If path was renamed, porcelain format is `orig -> dest`
            if " -> " in file_path:
                file_path = file_path.split(" -> ")[1].strip()

            index_status = status_code[0]
            worktree_status = status_code[1]

            # Untracked
            if status_code == "??" or index_status == "?":
                untracked.append(file_path)
                continue

            # Staged changes (Index)
            if index_status in {"A", "M", "R", "C"}:
                staged.append(file_path)
            elif index_status == "D":
                staged.append(file_path)
                deleted.append(file_path)

            # Unstaged changes (Worktree)
            if worktree_status in {"M", "T"}:
                unstaged.append(file_path)
            elif worktree_status == "D":
                unstaged.append(file_path)
                deleted.append(file_path)

        is_dirty = bool(staged or unstaged or untracked or deleted)

        return {
            "is_dirty": is_dirty,
            "staged_files": sorted(list(set(staged))),
            "unstaged_files": sorted(list(set(unstaged))),
            "untracked_files": sorted(list(set(untracked))),
            "deleted_files": sorted(list(set(deleted)))
        }

    def get_staged_diff(self, root_path: Path) -> str:
        """Retrieves raw diff of staged changes."""
        code, out, _ = self._run_git_command(root_path, ["diff", "--cached"])
        return out.strip() if code == 0 else ""

    def get_unstaged_diff(self, root_path: Path) -> str:
        """Retrieves raw diff of unstaged working tree changes."""
        code, out, _ = self._run_git_command(root_path, ["diff"])
        return out.strip() if code == 0 else ""

    def get_recent_commits(self, root_path: Path, max_count: int = 15) -> List[Dict[str, Any]]:
        """
        Retrieves recent commit log with SHA, author, timestamp, and message.
        """
        format_str = "%H%x1f%an%x1f%ae%x1f%aI%x1f%s"
        code, out, _ = self._run_git_command(
            root_path,
            ["log", f"-n{max_count}", f"--pretty=format:{format_str}"]
        )
        if code != 0 or not out:
            return []

        commits: List[Dict[str, Any]] = []
        for line in out.splitlines():
            parts = line.split("\x1f")
            if len(parts) >= 5:
                commits.append({
                    "commit_hash": parts[0],
                    "author_name": parts[1],
                    "author_email": parts[2],
                    "authored_at": parts[3],
                    "subject": parts[4]
                })

        return commits

    def get_file_churn(self, root_path: Path, max_commits: int = 20) -> Dict[str, Dict[str, int]]:
        """
        Calculates file modification churn (insertions, deletions, modification count).
        """
        code, out, _ = self._run_git_command(
            root_path,
            ["log", f"-n{max_commits}", "--numstat", "--pretty=format:"]
        )
        if code != 0 or not out:
            return {}

        churn: Dict[str, Dict[str, int]] = defaultdict(lambda: {"insertions": 0, "deletions": 0, "commits": 0})

        for line in out.splitlines():
            parts = line.strip().split()
            if len(parts) == 3:
                added_str, deleted_str, file_path = parts
                added = int(added_str) if added_str.isdigit() else 0
                deleted = int(deleted_str) if deleted_str.isdigit() else 0
                churn[file_path]["insertions"] += added
                churn[file_path]["deletions"] += deleted
                churn[file_path]["commits"] += 1

        return dict(churn)

    def extract(self, target_path_or_input: str, context: Optional[Dict[str, Any]] = None) -> List[Evidence]:
        root_path = Path(target_path_or_input).resolve()
        evidence_list: List[Evidence] = []

        if not self.is_git_repository(root_path):
            evidence_list.append(self.create_evidence(
                evidence_type=EvidenceType.GIT_STATUS,
                summary="Workspace is not a Git repository or Git is unavailable",
                raw_payload={"is_repo": False},
                source_uri=str(root_path),
                locator="git:none"
            ))
            return evidence_list

        branch, head_commit = self.get_head_info(root_path)
        status_info = self.get_working_tree_status(root_path)
        commits = self.get_recent_commits(root_path)
        churn = self.get_file_churn(root_path)

        # 1. Git Status Evidence
        status_summary = (
            f"Git repository on branch '{branch or 'unborn'}' (HEAD: {head_commit[:7] if head_commit else 'none'}). "
            f"Working tree is {'DIRTY' if status_info['is_dirty'] else 'CLEAN'} "
            f"({len(status_info['staged_files'])} staged, {len(status_info['unstaged_files'])} unstaged, {len(status_info['untracked_files'])} untracked)"
        )
        status_payload = {
            "is_repo": True,
            "branch": branch,
            "head_commit": head_commit,
            **status_info
        }
        evidence_list.append(self.create_evidence(
            evidence_type=EvidenceType.GIT_STATUS,
            summary=status_summary,
            raw_payload=status_payload,
            source_uri=str(root_path),
            locator="git:status"
        ))

        # 2. Git Commit History Evidence
        if commits:
            evidence_list.append(self.create_evidence(
                evidence_type=EvidenceType.GIT_COMMIT,
                summary=f"Recent Git commit history: {len(commits)} commits recorded",
                raw_payload={"commits": commits},
                source_uri=str(root_path),
                locator=f"git:commits:{head_commit[:7] if head_commit else 'all'}"
            ))

        # 3. Git Diff / Churn Evidence
        if churn:
            evidence_list.append(self.create_evidence(
                evidence_type=EvidenceType.GIT_DIFF,
                summary=f"Calculated file churn across recent commits for {len(churn)} files",
                raw_payload={"churn": churn},
                source_uri=str(root_path),
                locator="git:churn"
            ))

        return evidence_list

    def populate_project_state(self, root_dir: str, canonical_state: CanonicalProjectState) -> ProjectState:
        """Populates ProjectState.git_state and registers git evidence."""
        root_path = Path(root_dir).resolve()
        evidence_list = self.extract(str(root_path))

        is_repo = False
        branch = None
        head_commit = None
        is_dirty = False
        staged: List[str] = []
        unstaged: List[str] = []
        untracked: List[str] = []
        commits: List[Dict[str, Any]] = []

        for ev in evidence_list:
            canonical_state.add_evidence(ev)
            if ev.type == EvidenceType.GIT_STATUS:
                is_repo = ev.raw_payload.get("is_repo", False)
                branch = ev.raw_payload.get("branch")
                head_commit = ev.raw_payload.get("head_commit")
                is_dirty = ev.raw_payload.get("is_dirty", False)
                staged = ev.raw_payload.get("staged_files", [])
                unstaged = ev.raw_payload.get("unstaged_files", [])
                untracked = ev.raw_payload.get("untracked_files", [])
            elif ev.type == EvidenceType.GIT_COMMIT:
                commits = ev.raw_payload.get("commits", [])

        git_state = GitState(
            is_repo=is_repo,
            branch=branch,
            head_commit=head_commit,
            is_dirty=is_dirty,
            staged_files=staged,
            unstaged_files=unstaged,
            untracked_files=untracked,
            recent_commits=commits,
            evidence_ids=[ev.id for ev in evidence_list]
        )

        ps = canonical_state.project_state
        ps.git_state = git_state
        ps.evidence_ids.extend([ev.id for ev in evidence_list])
        return ps
