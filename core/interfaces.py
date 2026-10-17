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

from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple, Union, runtime_checkable

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


# ==============================================================================
# 8. CONTINUITY CORE INTERFACES (v1.4.0 — Milestone 41 / Phase 72)
# ==============================================================================

@runtime_checkable
class ILifecycleManager(Protocol):
    """Contract for Activity lifecycle operations and valid transitions."""
    def create_activity(self, activity: Any) -> Any:
        ...

    def get_activity(self, activity_id: str) -> Any:
        ...

    def update_activity(self, activity: Any) -> Any:
        ...

    def transition_activity_status(self, activity_id: str, new_status: Any, reason: Optional[str] = None) -> Any:
        ...

    def list_activities(
        self,
        status: Optional[Any] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Any], int]:
        ...


@runtime_checkable
class ICheckpointManager(Protocol):
    """Contract for durable checkpoint CRUD and atomic commit confirmation."""
    def commit_checkpoint(self, checkpoint: Any) -> Any:
        ...

    def get_checkpoint(self, checkpoint_id: str, activity_id: Optional[str] = None) -> Any:
        ...

    def list_checkpoints(
        self,
        activity_id: str,
        limit: int = 50,
        offset: int = 0,
        order: str = "desc",
    ) -> Tuple[List[Any], int]:
        ...


@runtime_checkable
class IResumeEngine(Protocol):
    """Contract for generating actionable continuity briefs and status answers."""
    def generate_brief(self, activity: Any, checkpoint: Any) -> Any:
        ...


@runtime_checkable
class IHistoryManager(Protocol):
    """Contract for read-only chronological timeline inspection and checkpoint comparison."""
    def get_timeline(self, activity_id: str, limit: int = 50, offset: int = 0) -> List[Any]:
        ...

    def compare_checkpoints(self, source_checkpoint: Any, target_checkpoint: Any) -> Any:
        ...


@runtime_checkable
class IBranchManager(Protocol):
    """Contract for creating isolated branch activities from historical checkpoints."""
    def branch_from_checkpoint(
        self,
        source_checkpoint_id: str,
        new_activity_title: str,
        branch_name: Optional[str] = None,
        source_activity_id: Optional[str] = None,
    ) -> Tuple[Any, Any]:
        ...

    def get_branch_ancestry(self, activity_id: str) -> Dict[str, Any]:
        ...


@runtime_checkable
class IRestoreManager(Protocol):
    """Contract for pre-flight restore inspection and safe history-preserving recovery."""
    def preview_restore(self, target_checkpoint_id: str, activity_id: Optional[str] = None) -> Dict[str, Any]:
        ...

    def confirm_restore(
        self,
        target_checkpoint_id: str,
        activity_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Tuple[Any, Any]:
        ...


@runtime_checkable
class IRetentionManager(Protocol):
    """Contract for safe history retention, pruning policy enforcement, and ancestry protection."""
    def evaluate_retention(self, activity_id: str, max_checkpoints: int = 100) -> Dict[str, Any]:
        ...

    def prune_checkpoints(self, activity_id: str, max_checkpoints: int = 100, dry_run: bool = True) -> Dict[str, Any]:
        ...


@runtime_checkable
class IIntegrityManager(Protocol):
    """Contract for storage consistency verification, orphan detection, and safe repair."""
    def audit(self) -> Any:
        ...

    def repair(self, dry_run: bool = False) -> Any:
        ...


@runtime_checkable
class IBackupManager(Protocol):
    """Contract for complete, disaster-recovery backup generation and integrity verification."""
    def create_backup(
        self,
        output_path: Optional[Union[str, Path]] = None,
        backup_name: Optional[str] = None
    ) -> Any:
        ...

    def verify_backup(self, archive_path: Union[str, Path], raise_on_error: bool = True) -> Any:
        ...

    def get_backup_scope(self) -> Dict[str, Any]:
        ...


