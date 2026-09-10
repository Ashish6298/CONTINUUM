"""
Project Continuum - Base Model Adapter
======================================
Milestone 6 - Phase 15: Model-Specific Handoff Adapters.
Defines base class for all AI platform adapters ensuring semantic consistency.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from core.enums import TargetModel, Status
from core.interfaces import IModelAdapter
from core.serializer import CanonicalStateSerializer
from core.state_models import CanonicalProjectState
from context.models import TaskContext


class BaseModelAdapter(ABC):
    """
    Abstract base adapter for AI model-specific handoff synthesis.
    Implements IModelAdapter protocol.
    """

    def __init__(self, target_model: TargetModel):
        self._target_model = target_model

    @property
    def target_model(self) -> TargetModel:
        return self._target_model

    @abstractmethod
    def generate_handoff(
        self,
        canonical_state: CanonicalProjectState,
        context_selection: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """
        Synthesizes model-specific handoff files dictionary:
        - "handoff.md": continuation briefing
        - "project-context.md": architectural narrative
        - "project-state.json": machine-readable payload
        """
        pass

    def _extract_verified_components(self, state: CanonicalProjectState) -> List[Dict[str, Any]]:
        """Returns list of verified physical components."""
        return [
            {
                "id": n.id,
                "name": n.name,
                "type": n.node_type.value,
                "status": n.status.value,
                "confidence": n.confidence_score
            }
            for n in state.graph_nodes.values()
            if n.status == Status.VERIFIED
        ]

    def _extract_unverified_claims(self, state: CanonicalProjectState) -> List[Dict[str, Any]]:
        """Returns list of unverified conversational agent claims."""
        return [
            {
                "id": c.id,
                "claim_text": c.claim_text,
                "claimed_status": c.claimed_status.value,
                "source_agent": c.source_agent
            }
            for c in state.conversational_state.agent_claims
        ]

    def _extract_active_contradictions(self, state: CanonicalProjectState) -> List[Dict[str, Any]]:
        """Returns list of unresolved contradictions."""
        return [
            {
                "id": c.id,
                "severity": c.severity,
                "explanation": c.explanation,
                "claim_text": c.claim_text,
                "resolved": c.resolved
            }
            for c in state.contradictions
            if not c.resolved
        ]

    def _extract_constraints(self, state: CanonicalProjectState) -> List[str]:
        """Extracts active constraints across architectural decisions."""
        constraints: List[str] = []
        for d in state.conversational_state.architectural_decisions:
            constraints.extend(d.constraints)
        return constraints
