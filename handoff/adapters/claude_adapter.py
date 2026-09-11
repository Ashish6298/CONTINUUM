"""
Project Continuum - Claude Handoff Adapter
==========================================
Milestone 6 - Phase 15: Model-Specific Handoff Adapters.
Formats handoff packages with semantic XML tags (<project_state>, <verified_reality>,
<active_blockers>, <tactical_tasks>) optimized for Claude 3 / 3.5 prompt caching and reasoning.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from core.enums import TargetModel, Status
from core.serializer import CanonicalStateSerializer
from core.state_models import CanonicalProjectState
from handoff.adapters.base import BaseModelAdapter


class ClaudeAdapter(BaseModelAdapter):
    """
    Handoff adapter tailored for Anthropic's Claude models.
    Uses structured XML tags for optimal context separation and prompt caching.
    """

    def __init__(self):
        super().__init__(target_model=TargetModel.CLAUDE)

    def generate_handoff(
        self,
        canonical_state: CanonicalProjectState,
        context_selection: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        # 1. project-state.json
        state_json = CanonicalStateSerializer.to_json(canonical_state, indent=2)

        # 2. project-context.md (XML structured)
        context_md = self._build_claude_context(canonical_state)

        # 3. handoff.md (XML tagged continuation briefing)
        handoff_md = self._build_claude_handoff(canonical_state, context_selection)

        return {
            "project-state.json": state_json,
            "project-context.md": context_md,
            "handoff.md": handoff_md
        }

    def _build_claude_context(self, state: CanonicalProjectState) -> str:
        p_state = state.project_state
        lines = [
            f"# Project Continuum — Architectural Context for Claude",
            f"<project_metadata>",
            f"  <project_id>{state.project_id}</project_id>",
            f"  <schema_version>{state.schema_version}</schema_version>",
            f"  <root_path>{p_state.root_path}</root_path>",
            f"  <languages>{', '.join(p_state.detected_languages)}</languages>",
            f"  <build_status>{p_state.build_status.value}</build_status>",
            f"</project_metadata>",
            "",
            "<verified_architecture>",
        ]

        for n in state.graph_nodes.values():
            lines.append(
                f"  <component id=\"{n.id}\" type=\"{n.node_type.value}\" status=\"{n.status.value}\" confidence=\"{n.confidence_score:.0f}%\">"
                f"{n.name}</component>"
            )

        lines.extend([
            "</verified_architecture>",
            "",
            "<test_verification_baseline>",
        ])

        for t in p_state.test_results:
            err_tag = f" error=\"{t.error_message}\"" if t.error_message else ""
            lines.append(
                f"  <test id=\"{t.test_id}\" suite=\"{t.suite}\" status=\"{t.status.value}\" exit_code=\"{t.exit_code}\"{err_tag}>"
                f"{t.name}</test>"
            )

        lines.extend([
            "</test_verification_baseline>",
            "",
            "<architectural_constraints>",
        ])

        for c in self._extract_constraints(state):
            lines.append(f"  <constraint>{c}</constraint>")

        lines.append("</architectural_constraints>")
        return "\n".join(lines)

    def _build_claude_handoff(
        self,
        state: CanonicalProjectState,
        context_selection: Optional[Dict[str, Any]] = None
    ) -> str:
        exec_state = state.agent_execution_state
        c_state = state.conversational_state

        lines = [
            "# Project Continuum — Claude Continuation Handoff",
            "",
            "<system_directives>",
            "  <directive>Preserve strict ontological separation between physical facts and conversational claims.</directive>",
            "  <directive>Never assume unverified agent claims are physically implemented without test verification.</directive>",
            "</system_directives>",
            "",
            "<active_tasks>",
        ]

        if exec_state.active_tasks:
            for t in exec_state.active_tasks:
                files_str = ", ".join(t.target_files) if t.target_files else "none"
                lines.append(f"  <task id=\"{t.id}\" status=\"{t.status.value}\" files=\"{files_str}\">{t.title}</task>")
        else:
            lines.append("  <task status=\"NONE\">No active in-flight tasks.</task>")

        lines.extend([
            "</active_tasks>",
            "",
            "<recommended_next_action>",
        ])

        if exec_state.next_action:
            na = exec_state.next_action
            lines.append(f"  <action type=\"{na.action_type}\" target=\"{na.target_uri}\">")
            lines.append(f"    <description>{na.description}</description>")
            if na.prerequisites:
                lines.append(f"    <prerequisites>{', '.join(na.prerequisites)}</prerequisites>")
            lines.append("  </action>")
        else:
            lines.append("  <action type=\"CONTINUE\">Resume highest priority in-progress component.</action>")

        lines.extend([
            "</recommended_next_action>",
            "",
            "<active_blockers_and_contradictions>",
        ])

        active_contra = self._extract_active_contradictions(state)
        if active_contra:
            for c in active_contra:
                lines.append(f"  <contradiction id=\"{c['id']}\" severity=\"{c['severity']}\">")
                lines.append(f"    <explanation>{c['explanation']}</explanation>")
                lines.append(f"    <claim>{c['claim_text']}</claim>")
                lines.append("  </contradiction>")
        else:
            lines.append("  <none>Zero unresolved contradictions detected.</none>")

        lines.extend([
            "</active_blockers_and_contradictions>",
            "",
            "<unverified_agent_claims>",
        ])

        for cl in c_state.agent_claims:
            lines.append(
                f"  <claim id=\"{cl.id}\" source=\"{cl.source_agent}\" status=\"{cl.claimed_status.value}\">"
                f"{cl.claim_text}</claim>"
            )

        lines.append("</unverified_agent_claims>")
        return "\n".join(lines)
