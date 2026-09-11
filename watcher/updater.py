"""
Project Continuum - Incremental State Updater
==============================================
Milestone 7 - Phase 16: Filesystem Observation & Incremental State Updates.
Applies detected workspace changes to CanonicalProjectState and the Canonical State Graph,
re-extracting only affected evidence and propagating invalidations.
"""

from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Set

from core.enums import NodeType, RelationType, Status
from core.state_models import (
    AstSymbol,
    CanonicalProjectState,
    GraphNode,
    ProjectState,
)
from extractors.parsers.python_parser import PythonParser
from extractors.parsers.js_ts_parser import JavaScriptTypeScriptParser
from extractors.parsers.comment_parser import CommentMarkerParser
from graph.manager import StateGraphManager
from watcher.models import ChangeType, FileChangeEvent, IncrementalUpdateResult


class IncrementalStateUpdater:
    """
    Applies fine-grained file changes to a CanonicalProjectState, updating
    symbols, files, and propagating invalidations through the StateGraph.
    """

    MAX_CHANGES_BEFORE_FALLBACK_FULL_SCAN = 50

    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root).resolve()
        self._python_parser = PythonParser()
        self._js_ts_parser = JavaScriptTypeScriptParser()

    def apply_changes(
        self,
        canonical_state: CanonicalProjectState,
        changes: List[FileChangeEvent],
        graph_manager: Optional[StateGraphManager] = None
    ) -> IncrementalUpdateResult:
        """
        Updates canonical_state in-place based on the list of file change events.
        """
        start_time = time.time()
        p_state = canonical_state.project_state

        # Fallback to full scan if too many simultaneous modifications occur
        if len(changes) > self.MAX_CHANGES_BEFORE_FALLBACK_FULL_SCAN:
            duration = (time.time() - start_time) * 1000.0
            return IncrementalUpdateResult(
                workspace_root=str(self.workspace_root),
                changes_processed=changes,
                full_scan_fallback_triggered=True,
                duration_ms=duration
            )

        re_extracted_symbols = 0
        removed_symbols = 0
        invalidated_nodes: Set[str] = set()
        propagated_stale_nodes: Set[str] = set()

        for change in changes:
            rel_path = change.file_path.replace("\\", "/")
            full_path = self.workspace_root / rel_path

            if change.change_type == ChangeType.DELETED:
                # 1. Remove file from files list
                if rel_path in p_state.files:
                    p_state.files.remove(rel_path)

                # 2. Remove all symbols belonging to this file
                old_sym_count = len(p_state.symbols)
                p_state.symbols = [s for s in p_state.symbols if s.file_path != rel_path]
                removed_symbols += (old_sym_count - len(p_state.symbols))

                # 3. Find associated graph node and mark STALE
                node_id = self._find_node_for_file(canonical_state, rel_path)
                if node_id:
                    invalidated_nodes.add(node_id)

            elif change.change_type in (ChangeType.CREATED, ChangeType.MODIFIED):
                # 1. Ensure file is in files list
                if rel_path not in p_state.files:
                    p_state.files.append(rel_path)

                # 2. Remove previous symbols for this file
                old_sym_count = len(p_state.symbols)
                p_state.symbols = [s for s in p_state.symbols if s.file_path != rel_path]
                removed_symbols += (old_sym_count - len(p_state.symbols))

                # 3. Re-extract symbols from file
                new_symbols = self._extract_file_symbols(full_path, rel_path)
                p_state.symbols.extend(new_symbols)
                re_extracted_symbols += len(new_symbols)

                # 4. Find associated graph node
                node_id = self._find_node_for_file(canonical_state, rel_path)
                if node_id:
                    invalidated_nodes.add(node_id)

        # Invalidate graph nodes and propagate STALE downstream if graph_manager provided
        if graph_manager:
            for n_id in invalidated_nodes:
                if n_id in canonical_state.graph_nodes:
                    node = canonical_state.graph_nodes[n_id]
                    node.status = Status.STALE
                    affected = graph_manager.propagate_invalidation(n_id)
                    propagated_stale_nodes.update(affected)

        canonical_state.updated_at = datetime.now(timezone.utc).isoformat()
        p_state.last_scanned_at = datetime.now(timezone.utc).isoformat()

        duration = (time.time() - start_time) * 1000.0
        return IncrementalUpdateResult(
            workspace_root=str(self.workspace_root),
            changes_processed=changes,
            re_extracted_symbols_count=re_extracted_symbols,
            removed_symbols_count=removed_symbols,
            invalidated_node_ids=sorted(list(invalidated_nodes)),
            propagated_stale_node_ids=sorted(list(propagated_stale_nodes)),
            full_scan_fallback_triggered=False,
            duration_ms=duration
        )

    def _find_node_for_file(self, state: CanonicalProjectState, rel_path: str) -> Optional[str]:
        """Finds a graph node that directly references the given file."""
        file_stem = Path(rel_path).stem.lower()
        for node_id, node in state.graph_nodes.items():
            if node_id.lower() == file_stem or node.name.lower() == file_stem:
                return node_id
            if node.metadata.get("file_path") == rel_path:
                return node_id
        return None

    def _extract_file_symbols(self, full_path: Path, rel_path: str) -> List[AstSymbol]:
        """Extracts AST symbols for a single file."""
        if not full_path.exists():
            return []

        ext = full_path.suffix.lower()
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []

        symbols: List[AstSymbol] = []
        if ext == ".py":
            res = self._python_parser.parse_source(str(full_path), content)
            symbols.extend(res.symbols)
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            res = self._js_ts_parser.parse_source(str(full_path), content)
            symbols.extend(res.symbols)

        # Standardize relative paths
        for s in symbols:
            s.file_path = rel_path
        return symbols
