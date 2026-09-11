"""
Tests for Phase 3: Git History & Workspace Delta Analysis
=========================================================
Validates:
1. Handling non-git directories gracefully (is_repo=False).
2. Handling repositories with 0 commits (unborn HEAD).
3. Detecting clean and dirty working trees.
4. Correctly categorizing staged, unstaged, and untracked files.
5. Extracting recent commit history and subject lines.
6. Calculating file-level churn metrics.
7. Generating canonical Evidence records and populating ProjectState.git_state.
"""

from pathlib import Path
import subprocess
import tempfile
import unittest

from core.enums import EvidenceType, EvidenceLevel
from core.state_models import CanonicalProjectState
from extractors.git_extractor import GitEvidenceExtractor


class TestGitExtractor(unittest.TestCase):

    def _init_git_repo(self, path: Path) -> None:
        subprocess.run(["git", "init"], cwd=str(path), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        subprocess.run(["git", "config", "user.name", "Continuum Tester"], cwd=str(path), check=True)
        subprocess.run(["git", "config", "user.email", "tester@continuum.dev"], cwd=str(path), check=True)

    def test_non_git_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            extractor = GitEvidenceExtractor()

            self.assertFalse(extractor.is_git_repository(root))

            state = CanonicalProjectState()
            ps = extractor.populate_project_state(str(root), state)

            self.assertFalse(ps.git_state.is_repo)
            self.assertIsNone(ps.git_state.branch)
            self.assertIsNone(ps.git_state.head_commit)
            self.assertEqual(len(state.evidence_pool), 1)

    def test_empty_git_repository_zero_commits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._init_git_repo(root)

            extractor = GitEvidenceExtractor()
            self.assertTrue(extractor.is_git_repository(root))

            branch, head_commit = extractor.get_head_info(root)
            self.assertIsNone(head_commit)  # No commits yet

            status = extractor.get_working_tree_status(root)
            self.assertFalse(status["is_dirty"])

            commits = extractor.get_recent_commits(root)
            self.assertEqual(len(commits), 0)

            state = CanonicalProjectState()
            ps = extractor.populate_project_state(str(root), state)
            self.assertTrue(ps.git_state.is_repo)
            self.assertIsNone(ps.git_state.head_commit)
            self.assertFalse(ps.git_state.is_dirty)

    def test_clean_and_dirty_working_tree_with_staged_and_untracked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._init_git_repo(root)

            # 1. Initial Commit (Clean state)
            file1 = root / "README.md"
            file1.write_text("# Test Repo", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=str(root), check=True)
            subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(root), check=True)

            extractor = GitEvidenceExtractor()
            status_clean = extractor.get_working_tree_status(root)
            self.assertFalse(status_clean["is_dirty"])

            # 2. Stage a new file
            file2 = root / "staged.txt"
            file2.write_text("staged content", encoding="utf-8")
            subprocess.run(["git", "add", "staged.txt"], cwd=str(root), check=True)

            # 3. Modify tracked file (unstaged)
            file1.write_text("# Test Repo Modified", encoding="utf-8")

            # 4. Create untracked file
            file3 = root / "untracked.py"
            file3.write_text("print('hello')", encoding="utf-8")

            status_dirty = extractor.get_working_tree_status(root)
            self.assertTrue(status_dirty["is_dirty"])
            self.assertIn("staged.txt", status_dirty["staged_files"])
            self.assertIn("README.md", status_dirty["unstaged_files"])
            self.assertIn("untracked.py", status_dirty["untracked_files"])

            # 5. Populate ProjectState
            state = CanonicalProjectState()
            ps = extractor.populate_project_state(str(root), state)
            self.assertTrue(ps.git_state.is_repo)
            self.assertTrue(ps.git_state.is_dirty)
            self.assertIsNotNone(ps.git_state.head_commit)
            self.assertIn("staged.txt", ps.git_state.staged_files)
            self.assertIn("README.md", ps.git_state.unstaged_files)
            self.assertIn("untracked.py", ps.git_state.untracked_files)

            # Check evidence
            for ev in state.evidence_pool.values():
                self.assertTrue(ev.verify_integrity())
                self.assertEqual(ev.level, EvidenceLevel.LEVEL_3_GIT_STATE)

    def test_commit_history_and_churn(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._init_git_repo(root)

            # Commit 1
            f = root / "app.py"
            f.write_text("line 1\nline 2\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=str(root), check=True)
            subprocess.run(["git", "commit", "-m", "feat: create app"], cwd=str(root), check=True)

            # Commit 2
            f.write_text("line 1\nline 2\nline 3\nline 4\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=str(root), check=True)
            subprocess.run(["git", "commit", "-m", "feat: add lines 3 and 4"], cwd=str(root), check=True)

            extractor = GitEvidenceExtractor()
            commits = extractor.get_recent_commits(root, max_count=5)
            self.assertEqual(len(commits), 2)
            self.assertEqual(commits[0]["subject"], "feat: add lines 3 and 4")
            self.assertEqual(commits[1]["subject"], "feat: create app")

            churn = extractor.get_file_churn(root)
            self.assertIn("app.py", churn)
            self.assertGreater(churn["app.py"]["insertions"], 0)


if __name__ == "__main__":
    unittest.main()
