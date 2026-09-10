"""
Project Continuum - Confidence Calculation Engine
=================================================
Milestone 3 - Phase 8: Confidence Calculation & Status Evaluation.
Calculates explainable confidence metrics (0.0% to 100.0%) grounded in physical proof
and governed by contradiction caps and hierarchy constraints.
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from core.enums import EvidenceLevel, EvidenceType, NodeType, Status
from core.evidence import Evidence
from core.interfaces import IConfidenceCalculator
from core.state_models import (
    CanonicalProjectState,
    ContradictionRecord,
    GraphNode,
    ProjectState,
)
from confidence.models import ConfidenceBreakdown


class ConfidenceCalculator(IConfidenceCalculator):
    """
    Computes grounded confidence scores for nodes, components, tasks, and entire projects.
    
    Scoring Dimensions:
    - Implementation Presence (Level 2): 0 to 35 pts
    - Test Existence: 0 to 15 pts
    - Test Execution & Passing Status (Level 1): 0 to 30 pts
    - Git Working Tree Consistency (Level 3): 0 to 10 pts
    - Documentation Presence (Level 4): 0 to 10 pts
    
    Hard Upper Caps:
    - High-Severity Contradiction on target: Capped at MAX 20.0%
    - Medium-Severity Contradiction on target: Capped at MAX 50.0%
    - Conversational Claim only (0 physical evidence): Capped at MAX 15.0%
    """

    def calculate_node_confidence(
        self,
        node: GraphNode,
        evidence_pool: Dict[str, Evidence],
        contradictions: List[ContradictionRecord]
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Calculates confidence score for a GraphNode.
        Implements IConfidenceCalculator Protocol.
        """
        # Gather relevant evidence for this node
        node_evidence: List[Evidence] = []
        for ev_id in node.evidence_ids:
            if ev_id in evidence_pool:
                node_evidence.append(evidence_pool[ev_id])

        # Also search pool if evidence_ids was empty
        if not node_evidence:
            node_name_lower = node.name.lower()
            for ev in evidence_pool.values():
                if node_name_lower in ev.summary.lower() or node_name_lower in str(ev.raw_payload).lower():
                    node_evidence.append(ev)

        breakdown = self.evaluate_component_confidence(
            target_id=node.id,
            target_name=node.name,
            evidence_list=node_evidence,
            contradictions=contradictions
        )

        node.confidence_score = breakdown.final_score
        return breakdown.final_score, breakdown.to_dict()

    def evaluate_component_confidence(
        self,
        target_id: str,
        target_name: str,
        evidence_list: List[Evidence],
        contradictions: List[ContradictionRecord]
    ) -> ConfidenceBreakdown:
        """
        Evaluates multi-dimensional confidence breakdown for any target identifier/name.
        """
        breakdown = ConfidenceBreakdown(target_id=target_id)
        breakdown.contributing_evidence_ids = [e.id for e in evidence_list]

        if not evidence_list:
            # Check if there are active contradictions
            relevant_contradictions = self._get_relevant_contradictions(target_id, target_name, contradictions)
            breakdown.active_contradiction_ids = [c.id for c in relevant_contradictions]
            breakdown.final_score = 0.0
            breakdown.explanation = f"Target '{target_name or target_id}' has zero evidence. Confidence: 0.0%."
            return breakdown

        # Check for pure conversational evidence
        has_physical_evidence = any(
            e.level in {EvidenceLevel.LEVEL_1_RUNTIME_TEST, EvidenceLevel.LEVEL_2_CODE_AST, EvidenceLevel.LEVEL_3_GIT_STATE}
            for e in evidence_list
        )

        # 1. Implementation Presence (Max 35)
        for ev in evidence_list:
            if ev.type in {EvidenceType.SOURCE_CODE, EvidenceType.AST_SYMBOL}:
                # If valid AST without syntax errors
                if not ev.raw_payload.get("errors"):
                    breakdown.implementation_presence = 35.0
                else:
                    breakdown.implementation_presence = 15.0  # Partial due to errors
            elif ev.type == EvidenceType.CONFIG_FILE:
                breakdown.implementation_presence = max(breakdown.implementation_presence, 25.0)

        # 2. Test Existence (Max 15)
        has_tests = any(
            ev.type == EvidenceType.TEST_RUN or "test" in ev.summary.lower() or "test" in ev.raw_payload.get("file_path", "").lower()
            for ev in evidence_list
        )
        if has_tests:
            breakdown.test_existence = 15.0

        # 3. Test Execution Pass (Max 30)
        for ev in evidence_list:
            if ev.type in {EvidenceType.TEST_RUN, EvidenceType.BUILD_LOG, EvidenceType.RUNTIME_LOG}:
                exit_code = ev.raw_payload.get("exit_code", 0)
                if exit_code == 0:
                    breakdown.test_execution_pass = 30.0
                else:
                    breakdown.test_execution_pass = 0.0
                    breakdown.test_existence = 15.0  # Test exists but failed

        # 4. Git Consistency (Max 10)
        for ev in evidence_list:
            if ev.type == EvidenceType.GIT_STATUS:
                is_dirty = ev.raw_payload.get("is_dirty", False)
                if not is_dirty:
                    breakdown.git_consistency = 10.0
                else:
                    breakdown.git_consistency = 4.0
            elif ev.type in {EvidenceType.GIT_COMMIT, EvidenceType.GIT_DIFF}:
                breakdown.git_consistency = max(breakdown.git_consistency, 8.0)

        # 5. Documentation Presence (Max 10)
        for ev in evidence_list:
            if ev.type == EvidenceType.DOCUMENTATION or ev.level == EvidenceLevel.LEVEL_4_DOCUMENTATION:
                breakdown.documentation_presence = 10.0

        # Sum raw score
        raw = (
            breakdown.implementation_presence
            + breakdown.test_existence
            + breakdown.test_execution_pass
            + breakdown.git_consistency
            + breakdown.documentation_presence
        )
        breakdown.raw_score = raw

        # 6. Apply Contradiction Penalties and Hard Caps
        relevant_contradictions = self._get_relevant_contradictions(target_id, target_name, contradictions)
        breakdown.active_contradiction_ids = [c.id for c in relevant_contradictions]

        score = raw
        cap: Optional[float] = None

        if not has_physical_evidence:
            # Pure conversational claims without physical grounding capped at 15.0%
            cap = 15.0
            breakdown.contradiction_penalties += 20.0

        for contra in relevant_contradictions:
            if contra.severity == "HIGH":
                cap = min(cap, 20.0) if cap is not None else 20.0
                breakdown.contradiction_penalties += 50.0
            elif contra.severity == "MEDIUM":
                cap = min(cap, 50.0) if cap is not None else 50.0
                breakdown.contradiction_penalties += 25.0
            elif contra.severity == "LOW":
                breakdown.contradiction_penalties += 10.0

        score = max(0.0, score - breakdown.contradiction_penalties)
        if cap is not None:
            score = min(score, cap)
            breakdown.contradiction_cap = cap

        breakdown.final_score = round(min(100.0, score), 1)

        # 7. Compose detailed explainability rationale
        reasons = []
        if breakdown.implementation_presence > 0:
            reasons.append(f"Physical implementation verified (+{breakdown.implementation_presence:.0f}%)")
        if breakdown.test_existence > 0:
            reasons.append(f"Test suite exists (+{breakdown.test_existence:.0f}%)")
        if breakdown.test_execution_pass > 0:
            reasons.append(f"Automated tests passed (+{breakdown.test_execution_pass:.0f}%)")
        if breakdown.git_consistency > 0:
            reasons.append(f"Git state recorded (+{breakdown.git_consistency:.0f}%)")
        if breakdown.documentation_presence > 0:
            reasons.append(f"Documentation verified (+{breakdown.documentation_presence:.0f}%)")

        if not has_physical_evidence:
            reasons.append("Unbacked conversational claim capped at 15.0%")

        if cap is not None and cap < raw:
            reasons.append(f"Capped at {cap:.0f}% due to active contradictions ({len(relevant_contradictions)} detected)")

        breakdown.explanation = (
            f"Confidence {breakdown.final_score:.1f}% for '{target_name or target_id}'. "
            + "; ".join(reasons)
            + "."
        )

        return breakdown

    def calculate_project_confidence(
        self,
        canonical_state: CanonicalProjectState
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Calculates global aggregate project confidence and detailed telemetry.
        Implements IConfidenceCalculator Protocol.
        """
        scores: List[float] = []
        node_breakdowns: Dict[str, Any] = {}

        # 1. Evaluate registered graph nodes
        for node in canonical_state.graph_nodes.values():
            sc, bd = self.calculate_node_confidence(
                node=node,
                evidence_pool=canonical_state.evidence_pool,
                contradictions=canonical_state.contradictions
            )
            scores.append(sc)
            node_breakdowns[node.id] = bd

        # 2. Evaluate User Requirements
        req_scores = []
        for req in canonical_state.conversational_state.user_requirements:
            matching_ev = [
                ev for ev in canonical_state.evidence_pool.values()
                if req.title.lower() in ev.summary.lower()
                or (req.evidence_id and ev.id == req.evidence_id)
            ]
            bd = self.evaluate_component_confidence(
                target_id=req.id,
                target_name=req.title,
                evidence_list=matching_ev,
                contradictions=canonical_state.contradictions
            )
            req_scores.append(bd.final_score)
            scores.append(bd.final_score)

        # 3. Factor in Project Physical State metrics
        pstate = canonical_state.project_state
        has_code = len(pstate.files) > 0
        has_symbols = len(pstate.symbols) > 0
        test_pass_rate = 0.0
        if pstate.test_results:
            passed_tests = sum(1 for t in pstate.test_results if t.status == Status.VERIFIED)
            test_pass_rate = (passed_tests / len(pstate.test_results)) * 100.0

        if not scores:
            # Baseline calculation from project state if graph is not yet populated
            base_score = 0.0
            if has_code:
                base_score += 35.0
            if has_symbols:
                base_score += 15.0
            if pstate.test_results:
                base_score += (test_pass_rate * 0.35)
            if pstate.git_state.is_repo and not pstate.git_state.is_dirty:
                base_score += 15.0

            # Contradiction discount
            unresolved_high = sum(1 for c in canonical_state.contradictions if c.severity == "HIGH" and not c.resolved)
            unresolved_med = sum(1 for c in canonical_state.contradictions if c.severity == "MEDIUM" and not c.resolved)
            penalty = (unresolved_high * 25.0) + (unresolved_med * 10.0)
            final_project_score = round(max(0.0, min(100.0, base_score - penalty)), 1)
        else:
            final_project_score = round(sum(scores) / len(scores), 1)

        summary_data = {
            "project_confidence": final_project_score,
            "evaluated_node_count": len(scores),
            "unresolved_contradictions": len([c for c in canonical_state.contradictions if not c.resolved]),
            "test_pass_rate": round(test_pass_rate, 1),
            "has_physical_code": has_code,
            "has_ast_symbols": has_symbols,
            "node_breakdowns": node_breakdowns
        }

        return final_project_score, summary_data

    def _get_relevant_contradictions(
        self,
        target_id: str,
        target_name: str,
        contradictions: List[ContradictionRecord]
    ) -> List[ContradictionRecord]:
        """Filters contradictions related to the specific target."""
        relevant = []
        target_lower = (target_name or target_id).lower()

        for c in contradictions:
            if c.resolved:
                continue
            if c.claim_id == target_id:
                relevant.append(c)
            elif target_lower and (target_lower in c.explanation.lower() or target_lower in c.claim_text.lower()):
                relevant.append(c)

        return relevant
