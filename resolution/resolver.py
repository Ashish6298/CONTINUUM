"""
Project Continuum - Evidence Resolution Engine
==============================================
Milestone 3 - Phase 6: Truth Resolution & Seniority-Based Arbitration.
Resolves multi-source evidence into consistent, explainable conclusions
using the 5-level Evidence Hierarchy Matrix while preserving conflicting proof.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from core.enums import EvidenceLevel, EvidenceType, Status
from core.evidence import Evidence
from core.interfaces import IEvidenceResolver
from core.state_models import (
    AgentClaim,
    CanonicalProjectState,
    ProjectState,
    Requirement,
)


@dataclass
class EvidenceCandidate:
    """An individual piece of evidence evaluated for a specific target component/task."""
    evidence: Evidence
    inferred_status: Status
    level: EvidenceLevel
    relevance_weight: float = 1.0
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence.id,
            "evidence_type": self.evidence.type.value,
            "level": int(self.level.value),
            "inferred_status": self.inferred_status.value,
            "relevance_weight": self.relevance_weight,
            "notes": self.notes
        }


@dataclass
class ResolutionResult:
    """The synthesized resolution conclusion with complete audit provenance."""
    target_id: str
    resolved_status: Status
    winning_evidence: Optional[Evidence]
    competing_evidence: List[Evidence] = field(default_factory=list)
    conflict_detected: bool = False
    rationale: str = ""
    hierarchy_level_used: Optional[EvidenceLevel] = None
    all_candidates: List[EvidenceCandidate] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_id": self.target_id,
            "resolved_status": self.resolved_status.value,
            "winning_evidence_id": self.winning_evidence.id if self.winning_evidence else None,
            "competing_evidence_ids": [e.id for e in self.competing_evidence],
            "conflict_detected": self.conflict_detected,
            "rationale": self.rationale,
            "hierarchy_level_used": int(self.hierarchy_level_used.value) if self.hierarchy_level_used else None,
            "candidates": [c.to_dict() for c in self.all_candidates]
        }


class EvidenceResolver(IEvidenceResolver):
    """
    Arbitrates multi-source evidence based on the Seniority Matrix:
    Level 1: Runtime status & automated tests (Highest)
    Level 2: AST symbols, code syntax, package manifests
    Level 3: Git working tree status, staged/unstaged, commits
    Level 4: Architecture docs, comments, READMEs
    Level 5: Conversational statements and agent claims (Lowest)
    """

    def resolve_status(
        self,
        target_id: str,
        evidence_list: List[Evidence],
        claims: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[Status, Optional[Evidence], str]:
        """
        Implements IEvidenceResolver interface method.
        Returns (Status, WinningEvidence, Rationale).
        """
        res = self.resolve_candidates(target_id, evidence_list, claims)
        return res.resolved_status, res.winning_evidence, res.rationale

    def resolve_candidates(
        self,
        target_id: str,
        evidence_list: List[Evidence],
        claims: Optional[List[Dict[str, Any]]] = None
    ) -> ResolutionResult:
        """
        Full resolution returning complete ResolutionResult audit record.
        """
        if not evidence_list:
            # Check if only claims exist
            if claims:
                claim_statuses = [Status(c.get("claimed_status", Status.VERIFIED.value)) for c in claims]
                return ResolutionResult(
                    target_id=target_id,
                    resolved_status=Status.UNVERIFIED,
                    winning_evidence=None,
                    competing_evidence=[],
                    conflict_detected=False,
                    rationale=f"Target '{target_id}' has {len(claims)} conversational claim(s), but ZERO physical evidence. Classified as UNVERIFIED.",
                    hierarchy_level_used=EvidenceLevel.LEVEL_5_CONVERSATION
                )
            return ResolutionResult(
                target_id=target_id,
                resolved_status=Status.UNKNOWN,
                winning_evidence=None,
                competing_evidence=[],
                conflict_detected=False,
                rationale=f"No evidence or claims available for '{target_id}'. Classified as UNKNOWN.",
                hierarchy_level_used=None
            )

        # 1. Classify each piece of evidence into candidates
        candidates: List[EvidenceCandidate] = []
        for ev in evidence_list:
            inferred_st, notes = self._infer_status_from_evidence(ev, target_id)
            candidates.append(EvidenceCandidate(
                evidence=ev,
                inferred_status=inferred_st,
                level=ev.level,
                notes=notes
            ))

        # 2. Sort candidates by Seniority (Level 1 < Level 2 < Level 3 < Level 4 < Level 5)
        candidates.sort(key=lambda c: (int(c.level.value), -c.relevance_weight))

        # 3. Detect Conflicts (do candidates disagree on success vs failure/pending?)
        distinct_statuses = {c.inferred_status for c in candidates if c.inferred_status != Status.UNKNOWN}
        has_conflict = len(distinct_statuses) > 1

        # 4. Group by highest seniority tier present
        highest_level = candidates[0].level
        top_tier_candidates = [c for c in candidates if c.level == highest_level]

        # 5. Arbitrate within top tier
        winning_candidate = self._arbitrate_tier(top_tier_candidates)
        winning_evidence = winning_candidate.evidence
        resolved_status = winning_candidate.inferred_status

        # 6. Compose explainability rationale
        competing = [c.evidence for c in candidates if c.evidence.id != winning_evidence.id]
        rationale = self._build_rationale(
            target_id=target_id,
            winning=winning_candidate,
            highest_level=highest_level,
            candidates=candidates,
            has_conflict=has_conflict
        )

        return ResolutionResult(
            target_id=target_id,
            resolved_status=resolved_status,
            winning_evidence=winning_evidence,
            competing_evidence=competing,
            conflict_detected=has_conflict,
            rationale=rationale,
            hierarchy_level_used=highest_level,
            all_candidates=candidates
        )

    def _infer_status_from_evidence(self, ev: Evidence, target_id: str) -> Tuple[Status, str]:
        """Infers the indicated status from an Evidence item."""
        payload = ev.raw_payload

        # Level 1: Test & Build results
        if ev.type in {EvidenceType.TEST_RUN, EvidenceType.BUILD_LOG, EvidenceType.RUNTIME_LOG}:
            exit_code = payload.get("exit_code", 0)
            if exit_code == 0:
                return Status.VERIFIED, f"Test/Build '{ev.summary}' passed (exit code 0)"
            else:
                return Status.FAILED, f"Test/Build '{ev.summary}' failed (exit code {exit_code})"

        # Level 2: Source Code & AST Symbols
        if ev.type == EvidenceType.AST_SYMBOL:
            symbols = payload.get("symbols", [])
            has_target = any(target_id.lower() in s.get("name", "").lower() for s in symbols) if target_id else bool(symbols)
            errors = payload.get("errors", [])
            if errors:
                return Status.FAILED, f"AST contains parse errors in {payload.get('file_path')}"
            if has_target:
                return Status.PARTIAL, f"AST symbol '{target_id}' found implemented in code"
            return Status.PARTIAL, f"Source code present ({len(symbols)} symbols)"

        if ev.type == EvidenceType.SOURCE_CODE:
            return Status.PARTIAL, f"Physical source file present: {payload.get('file_list', [])[:3]}"

        if ev.type == EvidenceType.CONFIG_FILE:
            return Status.VERIFIED, f"Configuration/manifest valid: {payload.get('manifest_type', 'config')}"

        # Level 3: Git State
        if ev.type == EvidenceType.GIT_STATUS:
            is_dirty = payload.get("is_dirty", False)
            if is_dirty:
                return Status.IN_PROGRESS, "Git working tree has uncommitted modifications in progress"
            return Status.VERIFIED, "Git repository working tree is clean and committed"

        if ev.type == EvidenceType.GIT_DIFF:
            return Status.IN_PROGRESS, "Git diff shows active in-flight code changes"

        if ev.type == EvidenceType.GIT_COMMIT:
            return Status.VERIFIED, "Git commit history records past changes"

        # Level 4: Documentation
        if ev.type == EvidenceType.DOCUMENTATION:
            return Status.UNVERIFIED, "Documented in markdown/README (requires code verification)"

        # Level 5: Conversational Assertions & Claims
        if ev.type in {EvidenceType.AGENT_CLAIM, EvidenceType.CONVERSATION_ASSERTION}:
            claimed_status = payload.get("claim", {}).get("claimed_status") or payload.get("claimed_status", Status.VERIFIED.value)
            return Status.UNVERIFIED, f"Agent claimed '{claimed_status}' in chat (unverified until physical proof is provided)"

        if ev.type == EvidenceType.USER_REQUIREMENT:
            return Status.PENDING, "User requirement defined in conversation (pending implementation)"

        return Status.UNKNOWN, "Unknown evidence type"

    def _arbitrate_tier(self, candidates: List[EvidenceCandidate]) -> EvidenceCandidate:
        """
        Arbitrates among candidates within the same seniority tier.
        Prioritizes hard failures over partial success (fail-safe verification principle).
        """
        # If any test failed within Level 1, failure takes precedence
        failing = [c for c in candidates if c.inferred_status == Status.FAILED]
        if failing:
            return failing[0]

        # Next prioritize verified
        verified = [c for c in candidates if c.inferred_status == Status.VERIFIED]
        if verified:
            return verified[0]

        # Otherwise return the highest weighted candidate
        return candidates[0]

    def _build_rationale(
        self,
        target_id: str,
        winning: EvidenceCandidate,
        highest_level: EvidenceLevel,
        candidates: List[EvidenceCandidate],
        has_conflict: bool
    ) -> str:
        level_names = {
            EvidenceLevel.LEVEL_1_RUNTIME_TEST: "Level 1 (Automated Test / Runtime)",
            EvidenceLevel.LEVEL_2_CODE_AST: "Level 2 (Source Code / AST / Manifest)",
            EvidenceLevel.LEVEL_3_GIT_STATE: "Level 3 (Git State / History)",
            EvidenceLevel.LEVEL_4_DOCUMENTATION: "Level 4 (Documentation)",
            EvidenceLevel.LEVEL_5_CONVERSATION: "Level 5 (Conversational Claims)"
        }

        tier_name = level_names.get(highest_level, f"Level {highest_level.value}")
        rationale = f"Resolved '{target_id}' to status [{winning.inferred_status.value}] via {tier_name}. {winning.notes}"

        if has_conflict:
            overridden = [c for c in candidates if c.level != highest_level]
            if overridden:
                overridden_desc = ", ".join([f"{level_names.get(c.level, 'L' + str(c.level.value))} ({c.inferred_status.value})" for c in overridden[:3]])
                rationale += f" Overrode conflicting lower-tier evidence: {overridden_desc}."

        return rationale

    def resolve_project_state(self, canonical_state: CanonicalProjectState) -> Dict[str, ResolutionResult]:
        """
        Runs comprehensive evidence resolution across all requirements, components,
        and agent claims registered in CanonicalProjectState.
        """
        results: Dict[str, ResolutionResult] = {}
        evidence_pool = canonical_state.evidence_pool

        # 1. Resolve User Requirements
        for req in canonical_state.conversational_state.user_requirements:
            matching_ev = [
                ev for ev in evidence_pool.values()
                if req.title.lower() in ev.summary.lower()
                or (req.evidence_id and ev.id == req.evidence_id)
            ]
            res = self.resolve_candidates(req.id, matching_ev)
            results[req.id] = res
            req.status = res.resolved_status

        # 2. Resolve Agent Claims
        for claim in canonical_state.conversational_state.agent_claims:
            target = claim.target_component or claim.claim_text
            matching_ev = [
                ev for ev in evidence_pool.values()
                if target.lower() in ev.summary.lower()
                or target.lower() in str(ev.raw_payload).lower()
            ]
            res = self.resolve_candidates(claim.id, matching_ev, claims=[claim.to_dict()])
            results[claim.id] = res

        # 3. Resolve AST Symbols
        for sym in canonical_state.project_state.symbols:
            matching_ev = [
                ev for ev in evidence_pool.values()
                if sym.name in ev.summary or (sym.evidence_id and ev.id == sym.evidence_id)
            ]
            res = self.resolve_candidates(sym.name, matching_ev)
            results[sym.name] = res

        return results
