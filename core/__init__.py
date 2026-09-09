"""
Project Continuum - Core Package Facade
======================================
Exposes primary models, enums, interfaces, and serializers.
"""

from core.enums import (
    Status,
    EvidenceType,
    EvidenceLevel,
    NodeType,
    RelationType,
    TargetModel,
)
from core.evidence import (
    Evidence,
    EvidenceProvenance,
)
from core.state_models import (
    ProjectState,
    ConversationalState,
    AgentExecutionState,
    CanonicalProjectState,
    AstSymbol,
    TestResult,
    GitState,
    ManifestInfo,
    Requirement,
    ArchitecturalDecision,
    AgentClaim,
    UnresolvedQuestion,
    TacticalTask,
    NextActionRecommendation,
    ContradictionRecord,
    GraphNode,
    GraphEdge,
)
from core.interfaces import (
    IEvidenceExtractor,
    IEvidenceResolver,
    IContradictionDetector,
    IConfidenceCalculator,
    IStateGraphManager,
    IContextSelector,
    IModelAdapter,
)
from core.schema import (
    CANONICAL_STATE_SCHEMA_VERSION,
    get_canonical_project_state_schema,
    validate_canonical_state_dict,
)
from core.serializer import (
    CanonicalStateSerializer,
    StateSerializationError,
    StateValidationError,
)

__all__ = [
    "Status",
    "EvidenceType",
    "EvidenceLevel",
    "NodeType",
    "RelationType",
    "TargetModel",
    "Evidence",
    "EvidenceProvenance",
    "ProjectState",
    "ConversationalState",
    "AgentExecutionState",
    "CanonicalProjectState",
    "AstSymbol",
    "TestResult",
    "GitState",
    "ManifestInfo",
    "Requirement",
    "ArchitecturalDecision",
    "AgentClaim",
    "UnresolvedQuestion",
    "TacticalTask",
    "NextActionRecommendation",
    "ContradictionRecord",
    "GraphNode",
    "GraphEdge",
    "IEvidenceExtractor",
    "IEvidenceResolver",
    "IContradictionDetector",
    "IConfidenceCalculator",
    "IStateGraphManager",
    "IContextSelector",
    "IModelAdapter",
    "CANONICAL_STATE_SCHEMA_VERSION",
    "get_canonical_project_state_schema",
    "validate_canonical_state_dict",
    "CanonicalStateSerializer",
    "StateSerializationError",
    "StateValidationError",
]
