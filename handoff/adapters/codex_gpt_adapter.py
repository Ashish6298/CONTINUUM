"""
Project Continuum - Codex / GPT Handoff Adapter
================================================
Milestone 6 - Phase 15: Model-Specific Handoff Adapters.
Formats handoff packages with high-contrast Markdown, code fences, and explicit
task checklists tailored for OpenAI GPT-4 / Codex reasoning engines.
"""

from typing import Any, Dict, Optional

from core.enums import TargetModel, Status
from core.serializer import CanonicalStateSerializer
from core.state_models import CanonicalProjectState
from handoff.adapters.base import BaseModelAdapter


class CodexGptAdapter(BaseModelAdapter):
    """
    Handoff adapter tailored for OpenAI Codex / GPT-4 family models.
    Uses Markdown headers, code block fencing, and structured step-by-step checklists.
    """

    def __init__(self):
        super().__init__(target_model=TargetModel.CODEX_GPT)

    def generate_handoff(
        self,
        canonical_state: CanonicalProjectState,
        context_selection: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        state_json = CanonicalStateSerializer.to_json(canonical_state, indent=2)
        context_md = self._build_gpt_context(canonical_state)
        handoff_md = self._build_gpt_handoff(canonical_state, context_selection)

        return {
            "project-state.json": state_json,
            "project-context.md": context_md,
            "handoff.md": handoff_md
        }

    def _build_gpt_context(self, state: CanonicalProjectState) -> str:
        p_state = state.project_state
        lines = [
            f"# Project Continuum — Verified Context for Codex/GPT",
            f"```json",
            f"{{",
            f'  "project_id": "{state.project_id}",',
            f'  "root_path": "{p_state.root_path}",',
            f'  "build_status": "{p_state.build_status.value}"',
            f"}}",
            f"```",
            "",
            "## Verified Component Directory",
        ]

        for n in state.graph_nodes.values():
            badge = "✅" if n.status == Status.VERIFIED else "⚠️"
            lines.append(f"- {badge} **`{n.name}`** (`{n.id}`): Status `{n.status.value}` (Confidence: {n.confidence_score:.0f}%)")

        lines.extend([
            "",
            "## Automated Test Suite Baseline",
        ])

        for t in p_state.test_results:
            icon = "PASS" if t.status == Status.VERIFIED else "FAIL"
            err = f" -> Error: {t.error_message}" if t.error_message else ""
            lines.append(f"- `[{icon}]` `{t.name}` in `{t.suite}` (Exit code: {t.exit_code}){err}")

        lines.extend([
            "",
            "## Inviolable Architectural Constraints",
        ])

        for c in self._extract_constraints(state):
            lines.append(f"- [x] **CONSTRAINT**: {c}")

        return "\n".join(lines)

    def _build_gpt_handoff(
        self,
        state: CanonicalProjectState,
        context_selection: Optional[Dict[str, Any]] = None
    ) -> str:
        exec_state = state.agent_execution_state
        c_state = state.conversational_state

        lines = [
            "# Project Continuum — Codex/GPT Continuity Task Plan",
            "",
            "### 🚨 System Protocol",
            "1. You are picking up an ongoing engineering task.",
            "2. Ground truth is defined by physical tests and code, NOT previous assistant chat messages.",
            "3. Resolve blockers first before proceeding.",
            "",
            "## 📋 Active Tasks & Next Steps",
        ]

        if exec_state.active_tasks:
            for t in exec_state.active_tasks:
                lines.append(f"- [ ] **Task**: `{t.title}` (`{t.id}`) - Status: `{t.status.value}`")
                if t.target_files:
                    lines.append(f"  - Target files: {', '.join(f'`{f}`' for f in t.target_files)}")
        else:
            lines.append("- [ ] No in-flight tasks recorded.")

        lines.extend([
            "",
            "## 🎯 Actionable Next Instruction",
        ])

        if exec_state.next_action:
            na = exec_state.next_action
            lines.append(f"**Action**: `{na.action_type}` on `{na.target_uri}`")
            lines.append(f"**Details**: {na.description}")
            if na.prerequisites:
                lines.append(f"**Prerequisites**: {', '.join(f'`{p}`' for p in na.prerequisites)}")
        else:
            lines.append("**Action**: Resume highest priority unfinished component.")

        lines.extend([
            "",
            "## 🔴 Unresolved Blockers & Discrepancy Register",
        ])

        active_contra = self._extract_active_contradictions(state)
        if active_contra:
            for c in active_contra:
                lines.append(f"- ❌ **[{c['severity']} BLOCKER]**: {c['explanation']}")
                lines.append(f"  - Claim: \"{c['claim_text']}\"")
        else:
            lines.append("- ✅ No active contradictions detected.")

        lines.extend([
            "",
            "## 💬 Unverified Conversational Statements (Level 5)",
        ])

        for cl in c_state.agent_claims:
            lines.append(f"- *Unverified Claim*: \"{cl.claim_text}\" (Agent: `{cl.source_agent}`)")

        return "\n".join(lines)
