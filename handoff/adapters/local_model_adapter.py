"""
Project Continuum - Local LLM Handoff Adapter
==============================================
Milestone 6 - Phase 15: Model-Specific Handoff Adapters.
Formats handoff packages in high-density, compact token-budget-optimized formats
for local models (e.g. Llama-3, Mistral, Qwen, DeepSeek Coder) with smaller context windows.
"""

from typing import Any, Dict, Optional

from core.enums import TargetModel, Status
from core.serializer import CanonicalStateSerializer
from core.state_models import CanonicalProjectState
from handoff.adapters.base import BaseModelAdapter


class LocalModelAdapter(BaseModelAdapter):
    """
    Handoff adapter tailored for local open-source LLMs.
    Prioritizes maximum information density and token frugality while strictly
    preserving Tier 1 constraints, blockers, and next actions.
    """

    def __init__(self):
        super().__init__(target_model=TargetModel.LOCAL_LLM)

    def generate_handoff(
        self,
        canonical_state: CanonicalProjectState,
        context_selection: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        # Compact JSON serialization (no extra whitespace)
        state_json = CanonicalStateSerializer.to_json(canonical_state, indent=2)
        context_md = self._build_compact_context(canonical_state)
        handoff_md = self._build_compact_handoff(canonical_state, context_selection)

        return {
            "project-state.json": state_json,
            "project-context.md": context_md,
            "handoff.md": handoff_md
        }

    def _build_compact_context(self, state: CanonicalProjectState) -> str:
        p_state = state.project_state
        lines = [
            f"# Context: {state.project_id} | Root: {p_state.root_path} | Build: [{p_state.build_status.value}]",
            "",
            "## Components",
        ]

        for n in state.graph_nodes.values():
            lines.append(f"- {n.name}({n.id}): [{n.status.value}] ({n.confidence_score:.0f}%)")

        lines.extend([
            "",
            "## Test Baseline",
        ])

        for t in p_state.test_results:
            err = f" Err:{t.error_message}" if t.error_message else ""
            lines.append(f"- {t.name}: [{t.status.value}] code:{t.exit_code}{err}")

        lines.extend([
            "",
            "## Active Constraints",
        ])

        for c in self._extract_constraints(state):
            lines.append(f"- ! {c}")

        return "\n".join(lines)

    def _build_compact_handoff(
        self,
        state: CanonicalProjectState,
        context_selection: Optional[Dict[str, Any]] = None
    ) -> str:
        exec_state = state.agent_execution_state
        c_state = state.conversational_state

        lines = [
            f"# Handoff | PrevAgent: {exec_state.model_name}",
            "! RULE: Physical reality overrides chat claims. Tests define ground truth.",
            "",
            "## In-Flight Tasks",
        ]

        if exec_state.active_tasks:
            for t in exec_state.active_tasks:
                files = f" files={','.join(t.target_files)}" if t.target_files else ""
                lines.append(f"- [{t.status.value}] {t.title} ({t.id}){files}")
        else:
            lines.append("- (none)")

        lines.extend([
            "",
            "## Next Action",
        ])

        if exec_state.next_action:
            na = exec_state.next_action
            lines.append(f"- Action: {na.action_type} | Target: {na.target_uri}")
            lines.append(f"  Note: {na.description}")
        else:
            lines.append("- Action: Continue incomplete components.")

        lines.extend([
            "",
            "## Blockers & Discrepancies",
        ])

        active_contra = self._extract_active_contradictions(state)
        if active_contra:
            for c in active_contra:
                lines.append(f"- BLOCKER [{c['severity']}]: {c['explanation']}")
        else:
            lines.append("- (none)")

        lines.extend([
            "",
            "## Unverified Claims",
        ])

        if c_state.agent_claims:
            for cl in c_state.agent_claims:
                lines.append(f"- Claim: \"{cl.claim_text}\" (Agent:{cl.source_agent})")
        else:
            lines.append("- (none)")

        return "\n".join(lines)
