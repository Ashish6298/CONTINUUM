"""
Project Continuum - Architectural Interfaces and Contracts
===========================================================
Defines the abstract Protocols / Interfaces for all major subsystems
across Project Continuum:
1. IEvidenceExtractor (Phases 1-5)
2. IEvidenceResolver (Phase 6)
3. IContradictionDetector (Phase 7)
4. IConfidenceCalculator (Phase 8)
5. IStateGraphManager (Phases 9-11)
6. IContextSelector (Phases 12-13)
7. IModelAdapter (Phases 14-15)
"""

from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from core.enums import EvidenceType, Status, TargetModel
from core.evidence import Evidence
from core.state_models import (
    CanonicalProjectState,
    ContradictionRecord,
    GraphEdge,
    GraphNode,
    ProjectState,
    ConversationalState,
    AgentExecutionState
)


# ==============================================================================
# 1. EVIDENCE EXTRACTOR INTERFACE
# ==============================================================================

@runtime_checkable
class IEvidenceExtractor(Protocol):
    """
    Contract implemented by all evidence extractors (Workspace/AST, Config,
    Git, Verification/Tests, Conversation).
    """
    @property
    def extractor_name(self) -> str:
        """Unique identifier for this extractor."""
        ...

    @property
    def supported_evidence_types(self) -> List[EvidenceType]:
        """Evidence types this extractor produces."""
        ...

    def can_extract(self, target_path_or_input: str) -> bool:
        """Determines if this extractor is applicable to the target."""
        ...

    def extract(self, target_path_or_input: str, context: Optional[Dict[str, Any]] = None) -> List[Evidence]:
        """Harvests verifiable evidence from the target."""
        ...


# ==============================================================================
# 2. EVIDENCE RESOLUTION INTERFACE
# ==============================================================================

@runtime_checkable
class IEvidenceResolver(Protocol):
    """
    Contract for arbitrating conflicting evidence according to the Evidence Hierarchy Matrix.
    """
    def resolve_status(
        self,
        target_id: str,
        evidence_list: List[Evidence],
        claims: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[Status, Optional[Evidence], str]:
        """
        Resolves candidate evidence into a final status.
        Returns (Status, WinningEvidence, RationaleExplanation).
        """
        ...


# ==============================================================================
# 3. CONTRADICTION DETECTOR INTERFACE
# ==============================================================================

@runtime_checkable
class IContradictionDetector(Protocol):
    """
    Contract for finding mismatches between claims/docs and physical reality.
    """
    def detect_contradictions(
        self,
        project_state: ProjectState,
        conversational_state: ConversationalState,
        evidence_pool: Dict[str, Evidence]
    ) -> List[ContradictionRecord]:
        """Analyzes all state dimensions and returns detected contradictions."""
        ...


# ==============================================================================
# 4. CONFIDENCE CALCULATOR INTERFACE
# ==============================================================================

@runtime_checkable
class IConfidenceCalculator(Protocol):
    """
    Contract for calculating explainable confidence scores (0.0% to 100.0%)
    grounded in physical proof and capped by contradictions.
    """
    def calculate_node_confidence(
        self,
        node: GraphNode,
        evidence_pool: Dict[str, Evidence],
        contradictions: List[ContradictionRecord]
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Calculates confidence score for a node and returns (Score, ExplanationDict).
        """
        ...

    def calculate_project_confidence(
        self,
        canonical_state: CanonicalProjectState
    ) -> Tuple[float, Dict[str, Any]]:
        """Calculates global aggregate project confidence."""
        ...


# ==============================================================================
# 5. STATE GRAPH MANAGER INTERFACE
# ==============================================================================

@runtime_checkable
class IStateGraphManager(Protocol):
    """
    Contract for managing the Directed Acyclic Graph (DAG) of the project.
    """
    def add_node(self, node: GraphNode) -> None:
        ...

    def add_edge(self, edge: GraphEdge) -> None:
        ...

    def get_dependencies(self, node_id: str, recursive: bool = False) -> List[GraphNode]:
        ...

    def get_dependents(self, node_id: str, recursive: bool = False) -> List[GraphNode]:
        ...

    def detect_cycles(self) -> List[List[str]]:
        ...

    def propagate_invalidation(self, changed_node_id: str) -> List[str]:
        """Marks downstream dependent nodes STALE or BLOCKED and returns affected IDs."""
        ...

    def export_mermaid(self) -> str:
        """Generates Mermaid diagram string representing the DAG."""
        ...


# ==============================================================================
# 6. CONTEXT SELECTOR INTERFACE
# ==============================================================================

@runtime_checkable
class IContextSelector(Protocol):
    """
    Contract for pruning unnecessary context and extracting the targeted subgraph
    for the next task.
    """
    def select_context_for_task(
        self,
        task_description: str,
        canonical_state: CanonicalProjectState,
        token_budget: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Returns targeted subgraph, relevant files, test references, constraints,
        and an audit of omitted items.
        """
        ...


# ==============================================================================
# 7. MODEL ADAPTER INTERFACE
# ==============================================================================

@runtime_checkable
class IModelAdapter(Protocol):
    """
    Contract for generating model-specific handoff packages (Claude, Codex, Gemini, Local).
    """
    @property
    def target_model(self) -> TargetModel:
        ...

    def generate_handoff(
        self,
        canonical_state: CanonicalProjectState,
        context_selection: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """
        Synthesizes the handoff files:
        - "handoff.md": continuation briefing
        - "project-context.md": architectural narrative
        - "project-state.json": machine-readable payload
        """
        ...
