"""
Project Continuum - Gemini Handoff Adapter
==========================================
Milestone 6 - Phase 15: Model-Specific Handoff Adapters.
Formats handoff packages with deep hierarchical structures, ontological groupings,
and rich contextual linkages optimized for Google Gemini 1.5 Pro / Flash large context windows.
"""

from typing import Any, Dict, Optional

from core.enums import TargetModel, Status
from core.serializer import CanonicalStateSerializer
from core.state_models import CanonicalProjectState
from handoff.adapters.base import BaseModelAdapter


class GeminiAdapter(BaseModelAdapter):
    """
    Handoff adapter tailored for Google Gemini models.
    Leverages deep hierarchical ontology representation and comprehensive cross-referencing.
    """

    def __init__(self):
        super().__init__(target_model=TargetModel.GEMINI)

    def generate_handoff(
        self,
        canonical_state: CanonicalProjectState,
        context_selection: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        state_json = CanonicalStateSerializer.to_json(canonical_state, indent=2)
        context_md = self._build_gemini_context(canonical_state)
        handoff_md = self._build_gemini_handoff(canonical_state, context_selection)

        return {
            "project-state.json": state_json,
            "project-context.md": context_md,
            "handoff.md": handoff_md
        }

    def _build_gemini_context(self, state: CanonicalProjectState) -> str:
        p_state = state.project_state
        lines = [
            f"# Project Continuum — Hierarchical Project Knowledge Graph (Gemini Engine)",
            f"**Canonical State Container:** `{state.project_id}` (Schema: `{state.schema_version}`)",
            "",
            "## Tier 1: Ground Truth Project Topology",
            "### Physical Environment & Manifests",
            f"- Path: `{p_state.root_path}`",
            f"- Polyglot Stack: {', '.join(p_state.detected_languages)}",
            f"- Build Status: `[{p_state.build_status.value}]`",
            "",
            "### Domain Component Graph",
        ]

        for n in state.graph_nodes.values():
            lines.append(f"- **{n.name}** (`{n.id}`) — Type: `{n.node_type.value}`, State: `{n.status.value}`, Verified Confidence: `{n.confidence_score:.1f}%`")

        lines.extend([
            "",
            "## Tier 2: Empirical Verification & Evidence Matrix",
            f"Total Verifiable Test Runs: {len(p_state.test_results)}",
        ])

        for t in p_state.test_results:
            status_symbol = "🟢" if t.status == Status.VERIFIED else "🔴"
            lines.append(f"{status_symbol} **{t.name}** (`{t.suite}`) | Exit Code: {t.exit_code} | Duration: {t.duration_ms:.1f}ms")
            if t.error_message:
                lines.append(f"   ↳ *Failure Reason:* `{t.error_message}`")

        lines.extend([
            "",
            "## Tier 3: Invariant Architectural Principles",
        ])

        for c in self._extract_constraints(state):
            lines.append(f"• **Hard Constraint:** {c}")

        return "\n".join(lines)

    def _build_gemini_handoff(
        self,
        state: CanonicalProjectState,
        context_selection: Optional[Dict[str, Any]] = None
    ) -> str:
        exec_state = state.agent_execution_state
        c_state = state.conversational_state

        lines = [
            "# Project Continuum — Gemini Agent Handoff & Continuity Instruction",
            "",
            "> 📌 **Epistemic Principle:**",
            "> Strict demarcation between empirical facts (code, tests) and linguistic assertions (chat claims).",
            "> Do not hallucinate task completion based on unverified conversational assertions.",
            "",
            "## 1. Tactical Execution Queue",
        ]

        if exec_state.active_tasks:
            for t in exec_state.active_tasks:
                lines.append(f"* **Active Task [{t.status.value}]:** `{t.title}` (`{t.id}`)")
                if t.target_files:
                    lines.append(f"  * Scoped Files: {', '.join(f'`{f}`' for f in t.target_files)}")
        else:
            lines.append("* *No in-flight tactical tasks.*")

        lines.extend([
            "",
            "## 2. Deterministic Next Action",
        ])

        if exec_state.next_action:
            na = exec_state.next_action
            lines.append(f"* **Type:** `{na.action_type}`")
            lines.append(f"* **Target:** `{na.target_uri}`")
            lines.append(f"* **Description:** {na.description}")
            if na.prerequisites:
                lines.append(f"* **Prerequisites:** {', '.join(f'`{p}`' for p in na.prerequisites)}")
        else:
            lines.append("* **Type:** `RESUME_PRIORITY_TASK`")

        lines.extend([
            "",
            "## 3. Discrepancy & Contradiction Registry",
        ])

        active_contra = self._extract_active_contradictions(state)
        if active_contra:
            for c in active_contra:
                lines.append(f"* ⚠️ **[{c['severity']}] Discrepancy:** {c['explanation']}")
                lines.append(f"  * Conflicting Assertion: \"{c['claim_text']}\"")
        else:
            lines.append("* ✅ *No unresolved discrepancies found.*")

        lines.extend([
            "",
            "## 4. Subjective Claims Register (Level 5)",
        ])

        for cl in c_state.agent_claims:
            lines.append(f"* *Claim:* \"{cl.claim_text}\" (Agent: `{cl.source_agent}`, Claimed: `[{cl.claimed_status.value}]`)")

        return "\n".join(lines)
