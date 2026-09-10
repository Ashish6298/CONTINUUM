"""
Project Continuum - Task-Driven Context Selection Engine
========================================================
Milestone 5 - Phase 12: Task-Driven Context Selection.
Identifies and extracts the minimum sufficient, high-signal project slice
required to execute a specific software development task.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from core.enums import NodeType, RelationType, Status
from core.interfaces import IContextSelector
from core.state_models import (
    ArchitecturalDecision,
    AstSymbol,
    CanonicalProjectState,
    ContradictionRecord,
    GraphNode,
    TestResult,
)
from context.models import TaskContext
from graph.manager import StateGraphManager


class TaskContextSelector(IContextSelector):
    """
    Selects task-specific project context from CanonicalProjectState and DAG.
    Implements IContextSelector Protocol.
    """

    STOP_WORDS = {
        "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "with",
        "by", "of", "is", "are", "be", "this", "that", "it", "from", "as", "fix",
        "add", "update", "implement", "create", "make", "refactor", "check", "test"
    }

    def select_context_for_task(
        self,
        task_description: str,
        canonical_state: CanonicalProjectState,
        token_budget: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extracts task-relevant context slice.
        Implements IContextSelector interface.
        """
        task_ctx = self.extract_task_context(task_description, canonical_state, token_budget)
        return task_ctx.to_dict()

    def extract_task_context(
        self,
        task_description: str,
        canonical_state: CanonicalProjectState,
        token_budget: Optional[int] = None
    ) -> TaskContext:
        """
        Returns strongly-typed TaskContext object.
        """
        # Build state graph manager
        graph_mgr = StateGraphManager(canonical_state)
        if not graph_mgr.nodes:
            graph_mgr.build_from_canonical_state(canonical_state)

        # 1. Extract keywords and semantic tokens from task prompt
        keywords = self._extract_keywords(task_description)

        # 2. Identify Primary Graph Nodes
        primary_nodes: List[GraphNode] = []
        matched_node_ids: Set[str] = set()

        for node in graph_mgr.nodes.values():
            node_name_clean = node.name.lower()
            if any(kw in node_name_clean for kw in keywords) or any(kw in node.id.lower() for kw in keywords):
                primary_nodes.append(node)
                matched_node_ids.add(node.id)

        # If no nodes matched directly, fall back to matching symbols or requirements
        if not primary_nodes and graph_mgr.nodes:
            primary_nodes = list(graph_mgr.nodes.values())[:3]
            for n in primary_nodes:
                matched_node_ids.add(n.id)

        # 3. Locate Direct Dependencies & Prerequisites
        dependency_nodes: List[GraphNode] = []
        dep_ids: Set[str] = set()

        for p_node in primary_nodes:
            # Direct dependencies
            deps = graph_mgr.get_dependencies(p_node.id, recursive=False)
            for d in deps:
                if d.id not in matched_node_ids and d.id not in dep_ids:
                    dependency_nodes.append(d)
                    dep_ids.add(d.id)

        # 4. Filter Relevant AST Symbols and Physical Files
        relevant_symbols: List[AstSymbol] = []
        relevant_files: Set[str] = set()

        all_target_names = {n.name.lower() for n in primary_nodes + dependency_nodes}
        all_target_names.update(keywords)

        for sym in canonical_state.project_state.symbols:
            sym_lower = sym.name.lower()
            if any(t in sym_lower or sym_lower in t for t in all_target_names):
                relevant_symbols.append(sym)
                relevant_files.add(sym.file_path)

        for f in canonical_state.project_state.files:
            f_lower = f.lower()
            if any(kw in f_lower for kw in keywords):
                relevant_files.add(f)

        # 5. Filter Relevant Test Results & Suites
        relevant_tests: List[TestResult] = []
        for t in canonical_state.project_state.test_results:
            t_lower = (t.name + " " + t.suite).lower()
            if any(t_name in t_lower for t_name in all_target_names):
                relevant_tests.append(t)
            elif t.status == Status.FAILED:
                # Include failing tests if they might relate
                relevant_tests.append(t)

        # Deduplicate tests
        unique_tests = []
        seen_test_ids = set()
        for t in relevant_tests:
            if t.test_id not in seen_test_ids:
                seen_test_ids.add(t.test_id)
                unique_tests.append(t)

        # 6. Locate Relevant Known Blockers & Contradictions
        relevant_blockers: List[ContradictionRecord] = []
        for c in canonical_state.contradictions:
            if not c.resolved:
                c_text = (c.claim_text + " " + c.explanation).lower()
                if any(t in c_text for t in all_target_names):
                    relevant_blockers.append(c)

        # 7. Extract Architectural Decisions & Active Constraints
        relevant_decisions: List[ArchitecturalDecision] = []
        active_constraints: List[str] = []

        for d in canonical_state.conversational_state.architectural_decisions:
            d_text = (d.title + " " + d.rationale).lower()
            if any(kw in d_text for kw in keywords):
                relevant_decisions.append(d)
                active_constraints.extend(d.constraints)

        # 8. Compute Omitted Node Count
        total_graph_nodes = len(graph_mgr.nodes)
        included_count = len(matched_node_ids) + len(dep_ids)
        omitted_count = max(0, total_graph_nodes - included_count)

        verification_summary = {
            "primary_node_count": len(primary_nodes),
            "dependency_node_count": len(dependency_nodes),
            "relevant_tests_count": len(unique_tests),
            "failing_tests_count": sum(1 for t in unique_tests if t.status == Status.FAILED),
            "active_blockers_count": len(relevant_blockers),
        }

        return TaskContext(
            task_description=task_description,
            primary_nodes=primary_nodes,
            dependency_nodes=dependency_nodes,
            relevant_files=sorted(list(relevant_files)),
            relevant_symbols=relevant_symbols,
            relevant_tests=unique_tests,
            active_constraints=active_constraints,
            relevant_decisions=relevant_decisions,
            known_blockers=relevant_blockers,
            verification_status_summary=verification_summary,
            omitted_node_count=omitted_count
        )

    def _extract_keywords(self, text: str) -> List[str]:
        """Extracts significant keywords and identifier tokens from prompt text."""
        # Find alphanumeric words with length >= 3
        words = re.findall(r"[A-Za-z0-9_]{3,}", text)
        keywords = [
            w.lower() for w in words
            if w.lower() not in self.STOP_WORDS
        ]
        return list(dict.fromkeys(keywords))  # Preserve order deduplication
