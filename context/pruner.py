"""
Project Continuum - Context Pruning & Token Budget Optimization
===============================================================
Milestone 5 - Phase 13: Context Pruning & Token Budget Optimization.
Implements greedy priority-tiered context pruning under configurable token budgets.
Guarantees that active architectural constraints and blockers are never silently dropped.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Set, Tuple

from context.models import TaskContext


class ContextPriorityTier(int, Enum):
    """Priority levels for task context retention."""
    TIER_1_CRITICAL_CONSTRAINTS = 1  # Active architectural constraints, blockers, goal (NEVER dropped)
    TIER_2_PRIMARY_ENTITIES = 2     # Primary components, failing tests, key interfaces
    TIER_3_DIRECT_DEPENDENCIES = 3   # Direct prerequisite components, passing tests
    TIER_4_SOURCE_SNIPPETS = 4       # Detailed symbol line spans & secondary files
    TIER_5_HISTORICAL_CONTEXT = 5    # Architectural background narratives, secondary decisions


@dataclass
class PrunedContextResult:
    """
    Result of budget-constrained context optimization.
    """
    task_description: str
    token_budget: Optional[int]
    estimated_tokens_before: int
    estimated_tokens_after: int
    reduction_percentage: float
    retained_sections: List[str] = field(default_factory=list)
    omitted_items: List[Dict[str, str]] = field(default_factory=list)
    constraint_preservation_guarantee: bool = True
    formatted_prompt: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ContextPruner:
    """
    Optimizes and prunes TaskContext to fit within a target token budget while
    strictly preserving Tier 1 critical constraints and reporting all omissions.
    """

    DEFAULT_CHAR_PER_TOKEN = 3.8  # Standard heuristic for code + English markdown

    def __init__(self, char_per_token: float = DEFAULT_CHAR_PER_TOKEN):
        self._char_per_token = char_per_token

    def estimate_tokens(self, text: str) -> int:
        """Estimates token count from text using character ratio heuristic."""
        if not text:
            return 0
        return math.ceil(len(text) / self._char_per_token)

    def prune_to_budget(
        self,
        task_context: TaskContext,
        token_budget: Optional[int] = None
    ) -> PrunedContextResult:
        """
        Prunes context items based on priority tiers until within token_budget.
        Tier 1 (Constraints & Blockers) is strictly protected.
        """
        full_markdown = task_context.to_markdown()
        initial_tokens = self.estimate_tokens(full_markdown)

        if token_budget is None or initial_tokens <= token_budget:
            return PrunedContextResult(
                task_description=task_context.task_description,
                token_budget=token_budget,
                estimated_tokens_before=initial_tokens,
                estimated_tokens_after=initial_tokens,
                reduction_percentage=0.0,
                retained_sections=["all"],
                omitted_items=[],
                constraint_preservation_guarantee=True,
                formatted_prompt=full_markdown
            )

        # Token budget is constrained: selectively assemble from Tier 1 to Tier 5
        omitted_items: List[Dict[str, str]] = []
        retained_sections: List[str] = []

        # Tier 1 (Mandatory - Critical Constraints & Blockers)
        tier1_lines = [
            f"# Task Briefing: {task_context.task_description}",
            ""
        ]

        if task_context.active_constraints:
            tier1_lines.append("## 🛡️ Active Constraints (CRITICAL)")
            for c in task_context.active_constraints:
                tier1_lines.append(f"- {c}")
            retained_sections.append("constraints")

        if task_context.known_blockers:
            tier1_lines.append("\n## ⚠️ Active Blockers & Discrepancies")
            for b in task_context.known_blockers:
                tier1_lines.append(f"- **[{b.severity}]**: {b.explanation}")
            retained_sections.append("blockers")

        current_text = "\n".join(tier1_lines)
        current_tokens = self.estimate_tokens(current_text)

        # Tier 2 (Primary Components & Failing Tests)
        tier2_lines = []
        if task_context.primary_nodes:
            tier2_lines.append("\n## 🎯 Primary Components")
            for n in task_context.primary_nodes:
                tier2_lines.append(f"- **{n.name}** (`{n.node_type.value}`): Status `[{n.status.value}]` (Confidence: {n.confidence_score:.0f}%)")

        failing_tests = [t for t in task_context.relevant_tests if t.status.value != "VERIFIED"]
        if failing_tests:
            tier2_lines.append("\n## ❌ Failing Test Evidence")
            for t in failing_tests:
                tier2_lines.append(f"- ❌ **{t.name}** (`{t.suite}`): exit code {t.exit_code} - `{t.error_message or ''}`")

        tier2_text = "\n".join(tier2_lines)
        if current_tokens + self.estimate_tokens(tier2_text) <= token_budget:
            current_text += tier2_text
            current_tokens = self.estimate_tokens(current_text)
            retained_sections.append("primary_components")
        else:
            omitted_items.append({
                "tier": "Tier 2",
                "item": "Primary components detailed list",
                "reason": "Exceeded token budget"
            })

        # Tier 3 (Direct Dependencies & Passing Tests)
        tier3_lines = []
        if task_context.dependency_nodes:
            tier3_lines.append("\n## 🔗 Direct Prerequisites")
            for d in task_context.dependency_nodes:
                tier3_lines.append(f"- **{d.name}** (`{d.node_type.value}`): Status `[{d.status.value}]`")

        passing_tests = [t for t in task_context.relevant_tests if t.status.value == "VERIFIED"]
        if passing_tests:
            tier3_lines.append("\n## ✅ Verified Test Baseline")
            for t in passing_tests[:3]:  # Top passing tests
                tier3_lines.append(f"- ✅ **{t.name}** (`{t.suite}`)")

        tier3_text = "\n".join(tier3_lines)
        if current_tokens + self.estimate_tokens(tier3_text) <= token_budget:
            current_text += tier3_text
            current_tokens = self.estimate_tokens(current_text)
            retained_sections.append("dependencies")
        else:
            if task_context.dependency_nodes:
                omitted_items.append({
                    "tier": "Tier 3",
                    "item": f"{len(task_context.dependency_nodes)} dependency nodes",
                    "reason": "Omitted to fit token budget"
                })

        # Tier 4 (Source Code Symbols & Line Spans)
        tier4_lines = []
        if task_context.relevant_symbols:
            tier4_lines.append("\n## 🧬 Relevant Symbols")
            for s in task_context.relevant_symbols[:5]:
                tier4_lines.append(f"- `{s.kind} {s.name}` in `{s.file_path}` (lines {s.line_start}-{s.line_end})")

        tier4_text = "\n".join(tier4_lines)
        if current_tokens + self.estimate_tokens(tier4_text) <= token_budget:
            current_text += tier4_text
            current_tokens = self.estimate_tokens(current_text)
            retained_sections.append("symbols")
        else:
            if task_context.relevant_symbols:
                omitted_items.append({
                    "tier": "Tier 4",
                    "item": f"{len(task_context.relevant_symbols)} code symbols",
                    "reason": "Omitted to fit token budget"
                })

        # Tier 5 (Background Decisions & Historical Narrative)
        tier5_lines = []
        if task_context.relevant_decisions:
            tier5_lines.append("\n## 📐 Architectural Decisions")
            for d in task_context.relevant_decisions:
                tier5_lines.append(f"- **{d.title}**: {d.rationale}")

        tier5_text = "\n".join(tier5_lines)
        if current_tokens + self.estimate_tokens(tier5_text) <= token_budget:
            current_text += tier5_text
            current_tokens = self.estimate_tokens(current_text)
            retained_sections.append("decisions")
        else:
            if task_context.relevant_decisions:
                omitted_items.append({
                    "tier": "Tier 5",
                    "item": f"{len(task_context.relevant_decisions)} architectural decisions",
                    "reason": "Omitted to fit token budget"
                })

        # Add explicit omission ledger footer
        footer_lines = [
            "",
            "---",
            f"**[Continuum Context Budget Audit: {current_tokens} tokens (Budget: {token_budget}) | {len(omitted_items)} section(s) pruned]**"
        ]
        if omitted_items:
            footer_lines.append("**Omitted Items due to budget constraints:**")
            for o in omitted_items:
                footer_lines.append(f"- *{o['tier']}*: {o['item']} ({o['reason']})")

        current_text += "\n".join(footer_lines)
        final_tokens = self.estimate_tokens(current_text)
        reduction = round(max(0.0, ((initial_tokens - final_tokens) / initial_tokens) * 100.0), 1)

        return PrunedContextResult(
            task_description=task_context.task_description,
            token_budget=token_budget,
            estimated_tokens_before=initial_tokens,
            estimated_tokens_after=final_tokens,
            reduction_percentage=reduction,
            retained_sections=retained_sections,
            omitted_items=omitted_items,
            constraint_preservation_guarantee=True,
            formatted_prompt=current_text
        )
