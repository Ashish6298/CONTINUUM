"""
Project Continuum - Universal Handoff Package Generator
========================================================
Milestone 6 - Phase 14: Universal Handoff Package Generation.
Generates standard vendor-neutral Continuum Handoff Packages that strictly
distinguish verified ground truth from conversational claims, report discrepancies,
blockers, confidence, and actionable next steps.
"""

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional

from core.enums import NodeType, Status
from core.serializer import CanonicalStateSerializer
from core.state_models import (
    CanonicalProjectState,
    ContradictionRecord,
    GraphNode,
    ProjectState,
    ConversationalState,
    AgentExecutionState,
)
from context.models import TaskContext
from handoff.models import HandoffPackage


class UniversalHandoffPackager:
    """
    Constructs vendor-neutral Continuum handoff packages containing:
    - project-state.json
    - project-context.md
    - handoff.md
    - evidence/ directory artifacts
    """

    def __init__(self):
        pass

    def generate_package(
        self,
        canonical_state: CanonicalProjectState,
        task_context: Optional[TaskContext] = None
    ) -> HandoffPackage:
        """
        Synthesizes the complete handoff package from a CanonicalProjectState and
        optional focused TaskContext.
        """
        # 1. Generate project-state.json (strict canonical schema)
        project_state_json = CanonicalStateSerializer.to_json(canonical_state, indent=2)

        # 2. Generate project-context.md (high-level verified architectural narrative)
        project_context_md = self._generate_project_context_md(canonical_state)

        # 3. Generate handoff.md (focused continuation briefing for the next agent)
        handoff_md = self._generate_handoff_md(canonical_state, task_context)

        # 4. Generate evidence/ directory artifacts
        evidence_files = self._generate_evidence_artifacts(canonical_state)

        metadata = {
            "schema_version": canonical_state.schema_version,
            "total_nodes": len(canonical_state.graph_nodes),
            "total_edges": len(canonical_state.graph_edges),
            "total_evidence": len(canonical_state.evidence_pool),
            "contradiction_count": len(canonical_state.contradictions),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        return HandoffPackage(
            project_id=canonical_state.project_id,
            package_timestamp=datetime.now(timezone.utc).isoformat(),
            project_state_json=project_state_json,
            project_context_md=project_context_md,
            handoff_md=handoff_md,
            evidence_files=evidence_files,
            metadata=metadata
        )

    def _generate_project_context_md(self, state: CanonicalProjectState) -> str:
        """
        Generates project-context.md: High-level architectural briefing of verified reality.
        """
        p_state = state.project_state
        c_state = state.conversational_state

        lines = [
            f"# Project Continuum — Verified Project Context",
            f"**Project ID:** `{state.project_id}` | **Schema:** `{state.schema_version}`",
            f"**Last Scanned:** `{p_state.last_scanned_at}`",
            "",
            "## 1. Physical Workspace Reality",
            f"- **Root Path:** `{p_state.root_path}`",
            f"- **Detected Languages:** {', '.join(p_state.detected_languages) if p_state.detected_languages else 'None detected'}",
            f"- **Source Files Tracked:** {len(p_state.files)} file(s)",
            f"- **AST Symbols Extracted:** {len(p_state.symbols)} symbol(s)",
            f"- **Build Status:** `[{p_state.build_status.value}]`",
            "",
            "### Git State",
            f"- **Repository:** {'Yes' if p_state.git_state.is_repo else 'No'}",
            f"- **Active Branch:** `{p_state.git_state.branch or 'N/A'}`",
            f"- **Head Commit:** `{p_state.git_state.head_commit or 'N/A'}`",
            f"- **Working Tree Dirty:** {'Yes (Uncommitted Changes)' if p_state.git_state.is_dirty else 'Clean'}",
            f"- **Staged Files:** {len(p_state.git_state.staged_files)}",
            f"- **Unstaged Files:** {len(p_state.git_state.unstaged_files)}",
            f"- **Untracked Files:** {len(p_state.git_state.untracked_files)}",
            "",
            "## 2. Canonical Architecture & Component Inventory",
        ]

        if state.graph_nodes:
            # Group by NodeType
            nodes_by_type: Dict[str, List[GraphNode]] = {}
            for n in state.graph_nodes.values():
                t = n.node_type.value
                nodes_by_type.setdefault(t, []).append(n)

            for n_type, n_list in sorted(nodes_by_type.items()):
                lines.append(f"### {n_type.capitalize()}s ({len(n_list)})")
                for n in sorted(n_list, key=lambda x: x.name):
                    conf_str = f" | Confidence: {n.confidence_score:.0f}%" if n.confidence_score > 0 else ""
                    lines.append(f"- **{n.name}** (`{n.id}`): Status `[{n.status.value}]`{conf_str}")
                lines.append("")
        else:
            lines.append("- *No graph components registered.*")
            lines.append("")

        lines.extend([
            "## 3. Verified Test & Verification Baseline",
            f"- **Recorded Test Executions:** {len(p_state.test_results)}",
        ])

        if p_state.test_results:
            passed = [t for t in p_state.test_results if t.status.value == "VERIFIED"]
            failed = [t for t in p_state.test_results if t.status.value != "VERIFIED"]
            lines.append(f"- **Passing Tests:** {len(passed)}")
            lines.append(f"- **Failing Tests:** {len(failed)}")
            if failed:
                lines.append("\n#### ❌ Failing Tests Detail:")
                for ft in failed:
                    lines.append(f"- **{ft.name}** (`{ft.suite}`): exit code {ft.exit_code}")
                    if ft.error_message:
                        lines.append(f"  - Error: `{ft.error_message}`")
        lines.append("")

        lines.extend([
            "## 4. Architectural Decisions & Requirements",
            f"- **User Requirements:** {len(c_state.user_requirements)}",
            f"- **Recorded Decisions:** {len(c_state.architectural_decisions)}",
        ])

        if c_state.architectural_decisions:
            for d in c_state.architectural_decisions:
                lines.append(f"- **{d.title}**: {d.rationale}")
                if d.constraints:
                    for c in d.constraints:
                        lines.append(f"  - *Constraint*: {c}")

        lines.append("\n---")
        lines.append("*Generated automatically by Project Continuum Universal Handoff Engine.*")
        return "\n".join(lines)

    def _generate_handoff_md(
        self,
        state: CanonicalProjectState,
        task_context: Optional[TaskContext] = None
    ) -> str:
        """
        Generates handoff.md: Tactical continuation document explaining exactly
        what the next agent needs to do, distinguishing verified vs unverified claims.
        """
        exec_state = state.agent_execution_state
        c_state = state.conversational_state
        p_state = state.project_state

        lines = [
            "# Project Continuum — Agent Handoff Briefing",
            f"**Session / Project ID:** `{state.project_id}`",
            f"**Previous Agent Model:** `{exec_state.model_name}` (ID: `{exec_state.agent_id}`)",
            f"**Handoff Generated At:** `{datetime.now(timezone.utc).isoformat()}`",
            "",
            "> ⚠️ **MANDATORY DIRECTIVE FOR RESUMING AGENT:**",
            "> Maintain strict separation between verified physical evidence and conversational claims.",
            "> Never accept unverified agent claims as completed tasks without physical verification.",
            "",
            "## 🎯 1. Tactical In-Flight & Active Tasks",
        ]

        if exec_state.active_tasks:
            for t in exec_state.active_tasks:
                lines.append(f"- **{t.title}** (`{t.id}`): Status `[{t.status.value}]`")
                if t.target_files:
                    lines.append(f"  - Target Files: {', '.join(f'`{f}`' for f in t.target_files)}")
                if t.target_symbols:
                    lines.append(f"  - Target Symbols: {', '.join(f'`{s}`' for s in t.target_symbols)}")
                if t.notes:
                    lines.append(f"  - Notes: {t.notes}")
        else:
            lines.append("- *No in-flight tasks recorded.*")

        lines.extend([
            "",
            "## 🚀 2. Recommended Next Action",
        ])

        if exec_state.next_action:
            na = exec_state.next_action
            lines.append(f"- **Action Type:** `{na.action_type}`")
            lines.append(f"- **Target URI:** `{na.target_uri}`")
            lines.append(f"- **Description:** {na.description}")
            if na.prerequisites:
                lines.append(f"- **Prerequisites:** {', '.join(f'`{p}`' for p in na.prerequisites)}")
        elif exec_state.last_error_encountered:
            lines.append(f"- **Action Required:** Fix last encountered error: `{exec_state.last_error_encountered}`")
        else:
            lines.append("- *Inspect known blockers and continue highest priority in-progress component.*")

        lines.extend([
            "",
            "## ⚠️ 3. Known Blockers & Contradiction Ledger",
        ])

        if state.contradictions:
            lines.append(f"**Total Contradictions Detected:** {len(state.contradictions)}")
            for c in state.contradictions:
                res_tag = " [RESOLVED]" if c.resolved else " [ACTIVE BLOCKER]"
                lines.append(f"- 🔴 **[{c.severity}]{res_tag}**: {c.explanation}")
                if c.claim_text:
                    lines.append(f"  - *Conflicting Claim*: \"{c.claim_text}\"")
        else:
            lines.append("- ✅ *Zero unresolved contradictions detected between claims and physical state.*")

        lines.extend([
            "",
            "## 💬 4. Unverified Conversational Claims & Unresolved Questions",
        ])

        if c_state.agent_claims:
            lines.append("### Unverified Agent Claims (Level 5 Evidence):")
            for cl in c_state.agent_claims:
                lines.append(f"- \"{cl.claim_text}\" (Claimed Status: `[{cl.claimed_status.value}]` by `{cl.source_agent}`)")
        else:
            lines.append("- *No unverified agent claims recorded.*")

        if c_state.unresolved_questions:
            lines.append("\n### Unresolved Questions:")
            for uq in c_state.unresolved_questions:
                block_tag = " **[BLOCKING]**" if uq.blocking else ""
                lines.append(f"- ❓{block_tag} {uq.question} (Context: {uq.context or 'N/A'})")

        if task_context:
            lines.extend([
                "",
                "## 🔍 5. Focused Task Context",
                task_context.to_markdown()
            ])

        lines.append("\n---")
        lines.append("*Project Continuum AI Work Continuity Package.*")
        return "\n".join(lines)

    def _generate_evidence_artifacts(self, state: CanonicalProjectState) -> Dict[str, str]:
        """
        Generates artifacts for the evidence/ directory:
        - evidence/test_results.json
        - evidence/contradictions.json
        - evidence/symbols_manifest.json
        - evidence/evidence_manifest.json
        """
        artifacts: Dict[str, str] = {}

        # 1. Test Results
        test_data = [t.to_dict() for t in state.project_state.test_results]
        artifacts["test_results.json"] = json.dumps(test_data, indent=2)

        # 2. Contradictions
        contra_data = [c.to_dict() for c in state.contradictions]
        artifacts["contradictions.json"] = json.dumps(contra_data, indent=2)

        # 3. Symbols
        sym_data = [s.to_dict() for s in state.project_state.symbols]
        artifacts["symbols_manifest.json"] = json.dumps(sym_data, indent=2)

        # 4. Evidence Pool Manifest
        ev_data = {k: v.to_dict() for k, v in state.evidence_pool.items()}
        artifacts["evidence_manifest.json"] = json.dumps(ev_data, indent=2)

        return artifacts
