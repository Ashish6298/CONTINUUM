"""
Project Continuum - Task Context Models
=======================================
Milestone 5 - Phase 12: Task-Driven Context Selection.
Defines the focused, task-scoped representation of project truth.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from core.state_models import (
    ArchitecturalDecision,
    AstSymbol,
    ContradictionRecord,
    GraphNode,
    TestResult,
)


@dataclass
class TaskContext:
    """
    Focused, high-signal project slice containing only information relevant to a target task.
    """
    task_description: str
    primary_nodes: List[GraphNode] = field(default_factory=list)
    dependency_nodes: List[GraphNode] = field(default_factory=list)
    relevant_files: List[str] = field(default_factory=list)
    relevant_symbols: List[AstSymbol] = field(default_factory=list)
    relevant_tests: List[TestResult] = field(default_factory=list)
    active_constraints: List[str] = field(default_factory=list)
    relevant_decisions: List[ArchitecturalDecision] = field(default_factory=list)
    known_blockers: List[ContradictionRecord] = field(default_factory=list)
    verification_status_summary: Dict[str, Any] = field(default_factory=dict)
    omitted_node_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_description": self.task_description,
            "primary_nodes": [n.to_dict() for n in self.primary_nodes],
            "dependency_nodes": [n.to_dict() for n in self.dependency_nodes],
            "relevant_files": self.relevant_files,
            "relevant_symbols": [s.to_dict() for s in self.relevant_symbols],
            "relevant_tests": [t.to_dict() for t in self.relevant_tests],
            "active_constraints": self.active_constraints,
            "relevant_decisions": [d.to_dict() for d in self.relevant_decisions],
            "known_blockers": [b.to_dict() for b in self.known_blockers],
            "verification_status_summary": self.verification_status_summary,
            "omitted_node_count": self.omitted_node_count
        }

    def to_markdown(self) -> str:
        """
        Formats the focused task context into a high-density, LLM-ready prompt briefing.
        """
        lines = [
            f"# Task Briefing: {self.task_description}",
            "",
            "## 🎯 Primary Components",
        ]

        if self.primary_nodes:
            for n in self.primary_nodes:
                lines.append(f"- **{n.name}** (`{n.node_type.value}`): Status `[{n.status.value}]` (Confidence: {n.confidence_score:.0f}%)")
        else:
            lines.append("- *No specific primary nodes identified.*")

        if self.dependency_nodes:
            lines.append("\n## 🔗 Dependencies & Direct Prerequisites")
            for d in self.dependency_nodes:
                lines.append(f"- **{d.name}** (`{d.node_type.value}`): Status `[{d.status.value}]`")

        if self.relevant_symbols:
            lines.append("\n## 🧬 Relevant Code Symbols & Interfaces")
            for s in self.relevant_symbols:
                lines.append(f"- `{s.kind} {s.name}` in `{s.file_path}` (lines {s.line_start}-{s.line_end})")

        if self.relevant_tests:
            lines.append("\n## 🧪 Verification & Test Status")
            for t in self.relevant_tests:
                status_icon = "✅" if t.status.value == "VERIFIED" else "❌"
                lines.append(f"- {status_icon} **{t.name}** (`{t.suite}`): `{t.status.value}` (exit code {t.exit_code})")
                if t.error_message:
                    lines.append(f"  - *Error*: `{t.error_message}`")

        if self.known_blockers:
            lines.append("\n## ⚠️ Known Blockers & Active Discrepancies")
            for b in self.known_blockers:
                lines.append(f"- **[{b.severity}]**: {b.explanation}")

        if self.active_constraints:
            lines.append("\n## 🛡️ Active Constraints")
            for c in self.active_constraints:
                lines.append(f"- {c}")

        if self.relevant_decisions:
            lines.append("\n## 📐 Architectural Decisions")
            for d in self.relevant_decisions:
                lines.append(f"- **{d.title}**: {d.rationale}")

        lines.append(f"\n*(Project Context Optimized: {self.omitted_node_count} unrelated nodes omitted)*")
        return "\n".join(lines)

    def prune(self, token_budget: int) -> Any:
        """Prunes this task context to fit within a specific token budget."""
        from context.pruner import ContextPruner
        pruner = ContextPruner()
        return pruner.prune_to_budget(self, token_budget=token_budget)
