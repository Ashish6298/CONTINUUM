"""
Project Continuum - Three-State Models & Canonical State
========================================================
Implements the core ontological separation between:
1. Project State (Physical Ground Truth)
2. Conversational State (Intent & Reasoning Claims)
3. Agent Execution State (Tactical In-Flight Intent)
and the aggregated CanonicalProjectState container.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from core.enums import Status, NodeType, RelationType, EvidenceLevel
from core.evidence import Evidence


# ==============================================================================
# 1. PROJECT STATE (PHYSICAL GROUND TRUTH)
# ==============================================================================

@dataclass
class AstSymbol:
    """Represents a code symbol extracted from AST (class, function, method, interface)."""
    name: str
    kind: str  # function, class, interface, method, variable
    file_path: str
    line_start: int
    line_end: int
    exported: bool = False
    docstring: Optional[str] = None
    parameters: List[str] = field(default_factory=list)
    return_type: Optional[str] = None
    evidence_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AstSymbol":
        return cls(**data)


@dataclass
class TestResult:
    """Represents a verifiable test execution result."""
    test_id: str
    name: str
    suite: str
    status: Status  # VERIFIED (passed) or FAILED
    exit_code: int
    duration_ms: float
    output_snippet: str = ""
    error_message: Optional[str] = None
    evidence_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TestResult":
        data_copy = dict(data)
        data_copy["status"] = Status(data_copy["status"])
        return cls(**data_copy)


@dataclass
class GitState:
    """Represents verifiable Git repository state."""
    is_repo: bool = False
    branch: Optional[str] = None
    head_commit: Optional[str] = None
    is_dirty: bool = False
    staged_files: List[str] = field(default_factory=list)
    unstaged_files: List[str] = field(default_factory=list)
    untracked_files: List[str] = field(default_factory=list)
    recent_commits: List[Dict[str, Any]] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GitState":
        return cls(**data)


@dataclass
class ManifestInfo:
    """Represents project manifests, package definitions, dependencies, and scripts."""
    manifest_type: str  # package.json, pyproject.toml, Cargo.toml, etc.
    file_path: str
    project_name: Optional[str] = None
    version: Optional[str] = None
    dependencies: Dict[str, str] = field(default_factory=dict)
    dev_dependencies: Dict[str, str] = field(default_factory=dict)
    scripts: Dict[str, str] = field(default_factory=dict)
    evidence_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ManifestInfo":
        return cls(**data)


@dataclass
class ProjectState:
    """
    State 1: Physical Reality of the Project.
    Contains solely physical facts derived from disk, Git, AST, tests, and builds.
    """
    root_path: str
    detected_languages: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    manifests: List[ManifestInfo] = field(default_factory=list)
    symbols: List[AstSymbol] = field(default_factory=list)
    git_state: GitState = field(default_factory=GitState)
    test_results: List[TestResult] = field(default_factory=list)
    build_status: Status = Status.UNKNOWN
    todo_markers: List[Dict[str, Any]] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    last_scanned_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root_path": self.root_path,
            "detected_languages": self.detected_languages,
            "files": self.files,
            "manifests": [m.to_dict() for m in self.manifests],
            "symbols": [s.to_dict() for s in self.symbols],
            "git_state": self.git_state.to_dict(),
            "test_results": [t.to_dict() for t in self.test_results],
            "build_status": self.build_status.value,
            "todo_markers": self.todo_markers,
            "evidence_ids": self.evidence_ids,
            "last_scanned_at": self.last_scanned_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectState":
        return cls(
            root_path=data.get("root_path", ""),
            detected_languages=data.get("detected_languages", []),
            files=data.get("files", []),
            manifests=[ManifestInfo.from_dict(m) for m in data.get("manifests", [])],
            symbols=[AstSymbol.from_dict(s) for s in data.get("symbols", [])],
            git_state=GitState.from_dict(data.get("git_state", {})),
            test_results=[TestResult.from_dict(t) for t in data.get("test_results", [])],
            build_status=Status(data.get("build_status", Status.UNKNOWN.value)),
            todo_markers=data.get("todo_markers", []),
            evidence_ids=data.get("evidence_ids", []),
            last_scanned_at=data.get("last_scanned_at", datetime.now(timezone.utc).isoformat())
        )


# ==============================================================================
# 2. CONVERSATIONAL STATE (INTENT & REASONING CLAIMS)
# ==============================================================================

@dataclass
class Requirement:
    id: str
    title: str
    description: str
    source_turn: Optional[int] = None
    status: Status = Status.PENDING
    evidence_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Requirement":
        d = dict(data)
        d["status"] = Status(d["status"])
        return cls(**d)


@dataclass
class ArchitecturalDecision:
    id: str
    title: str
    rationale: str
    constraints: List[str] = field(default_factory=list)
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    evidence_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArchitecturalDecision":
        return cls(**data)


@dataclass
class AgentClaim:
    """An unverified claim made by an AI model in chat (e.g. 'Payment service complete')."""
    id: str
    claim_text: str
    target_component: Optional[str] = None
    claimed_status: Status = Status.VERIFIED
    source_agent: str = "unknown_agent"
    turn_id: Optional[int] = None
    confidence_claimed: Optional[float] = None
    evidence_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["claimed_status"] = self.claimed_status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentClaim":
        d = dict(data)
        d["claimed_status"] = Status(d["claimed_status"])
        return cls(**d)


@dataclass
class UnresolvedQuestion:
    id: str
    question: str
    context: str = ""
    blocking: bool = False
    asked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    evidence_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnresolvedQuestion":
        return cls(**data)


@dataclass
class ConversationalState:
    """
    State 2: Intent, Decisions, and Claims from conversations.
    Kept strictly segregated from physical reality.
    """
    session_id: str = field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:8]}")
    user_requirements: List[Requirement] = field(default_factory=list)
    architectural_decisions: List[ArchitecturalDecision] = field(default_factory=list)
    agent_claims: List[AgentClaim] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    unresolved_questions: List[UnresolvedQuestion] = field(default_factory=list)
    transcript_provenance: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_requirements": [r.to_dict() for r in self.user_requirements],
            "architectural_decisions": [d.to_dict() for d in self.architectural_decisions],
            "agent_claims": [c.to_dict() for c in self.agent_claims],
            "assumptions": self.assumptions,
            "unresolved_questions": [q.to_dict() for q in self.unresolved_questions],
            "transcript_provenance": self.transcript_provenance
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationalState":
        return cls(
            session_id=data.get("session_id", f"sess_{uuid.uuid4().hex[:8]}"),
            user_requirements=[Requirement.from_dict(r) for r in data.get("user_requirements", [])],
            architectural_decisions=[ArchitecturalDecision.from_dict(d) for d in data.get("architectural_decisions", [])],
            agent_claims=[AgentClaim.from_dict(c) for c in data.get("agent_claims", [])],
            assumptions=data.get("assumptions", []),
            unresolved_questions=[UnresolvedQuestion.from_dict(q) for q in data.get("unresolved_questions", [])],
            transcript_provenance=data.get("transcript_provenance", [])
        )


# ==============================================================================
# 3. AGENT EXECUTION STATE (TACTICAL IN-FLIGHT INTENT)
# ==============================================================================

@dataclass
class TacticalTask:
    id: str
    title: str
    status: Status = Status.IN_PROGRESS
    target_files: List[str] = field(default_factory=list)
    target_symbols: List[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TacticalTask":
        d = dict(data)
        d["status"] = Status(d["status"])
        return cls(**d)


@dataclass
class NextActionRecommendation:
    action_type: str  # e.g., "EDIT_FILE", "RUN_TEST", "FIX_SYNTAX", "RESOLVE_CONTRADICTION"
    target_uri: str
    description: str
    prerequisites: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NextActionRecommendation":
        return cls(**data)


@dataclass
class AgentExecutionState:
    """
    State 3: What the previous AI was in the middle of executing.
    Tracks in-flight refactorings, modified files, transient errors, and next actions.
    """
    agent_id: str = "agent_unknown"
    model_name: str = "unknown"
    active_tasks: List[TacticalTask] = field(default_factory=list)
    modified_files_in_flight: List[str] = field(default_factory=list)
    last_error_encountered: Optional[str] = None
    next_action: Optional[NextActionRecommendation] = None
    execution_context_metadata: Dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "model_name": self.model_name,
            "active_tasks": [t.to_dict() for t in self.active_tasks],
            "modified_files_in_flight": self.modified_files_in_flight,
            "last_error_encountered": self.last_error_encountered,
            "next_action": self.next_action.to_dict() if self.next_action else None,
            "execution_context_metadata": self.execution_context_metadata,
            "updated_at": self.updated_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentExecutionState":
        next_act = NextActionRecommendation.from_dict(data["next_action"]) if data.get("next_action") else None
        return cls(
            agent_id=data.get("agent_id", "agent_unknown"),
            model_name=data.get("model_name", "unknown"),
            active_tasks=[TacticalTask.from_dict(t) for t in data.get("active_tasks", [])],
            modified_files_in_flight=data.get("modified_files_in_flight", []),
            last_error_encountered=data.get("last_error_encountered"),
            next_action=next_act,
            execution_context_metadata=data.get("execution_context_metadata", {}),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat())
        )


# ==============================================================================
# CANONICAL GRAPH NODES & CONTRADICTION MODELS
# ==============================================================================

@dataclass
class ContradictionRecord:
    """
    Represents an explicit discrepancy between claims/docs and physical reality.
    """
    id: str
    severity: str  # HIGH, MEDIUM, LOW
    claim_id: Optional[str] = None
    claim_text: str = ""
    physical_evidence_id: Optional[str] = None
    explanation: str = ""
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContradictionRecord":
        return cls(**data)


@dataclass
class GraphNode:
    """Node in the Canonical State Graph (DAG)."""
    id: str
    name: str
    node_type: NodeType
    status: Status = Status.UNKNOWN
    confidence_score: float = 0.0  # 0.0 to 100.0
    evidence_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "node_type": self.node_type.value,
            "status": self.status.value,
            "confidence_score": self.confidence_score,
            "evidence_ids": self.evidence_ids,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphNode":
        return cls(
            id=data["id"],
            name=data["name"],
            node_type=NodeType(data["node_type"]),
            status=Status(data.get("status", Status.UNKNOWN.value)),
            confidence_score=float(data.get("confidence_score", 0.0)),
            evidence_ids=data.get("evidence_ids", []),
            metadata=data.get("metadata", {})
        )


@dataclass
class GraphEdge:
    """Directed edge in the Canonical State Graph."""
    source_id: str
    target_id: str
    relation: RelationType

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation": self.relation.value
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphEdge":
        return cls(
            source_id=data["source_id"],
            target_id=data["target_id"],
            relation=RelationType(data["relation"])
        )


# ==============================================================================
# AGGREGATE CANONICAL PROJECT STATE (ROOT CONTAINER)
# ==============================================================================

@dataclass
class CanonicalProjectState:
    """
    Root container for the complete verified state of Project Continuum.
    Preserves versioning, strict state isolation, the canonical graph,
    contradictions, and all referenced evidence.
    """
    schema_version: str = "1.0.0"
    project_id: str = field(default_factory=lambda: f"proj_{uuid.uuid4().hex[:8]}")
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # The 3 segregated states:
    project_state: ProjectState = field(default_factory=lambda: ProjectState(root_path=""))
    conversational_state: ConversationalState = field(default_factory=ConversationalState)
    agent_execution_state: AgentExecutionState = field(default_factory=AgentExecutionState)

    # Global evidence pool indexed by evidence.id:
    evidence_pool: Dict[str, Evidence] = field(default_factory=dict)

    # Canonical State Graph (DAG):
    graph_nodes: Dict[str, GraphNode] = field(default_factory=dict)
    graph_edges: List[GraphEdge] = field(default_factory=list)

    # Discrepancies and Contradictions Ledger:
    contradictions: List[ContradictionRecord] = field(default_factory=list)

    def add_evidence(self, evidence: Evidence) -> str:
        """Registers a piece of evidence in the global pool and returns its ID."""
        self.evidence_pool[evidence.id] = evidence
        return evidence.id

    def get_evidence(self, evidence_id: str) -> Optional[Evidence]:
        return self.evidence_pool.get(evidence_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "project_state": self.project_state.to_dict(),
            "conversational_state": self.conversational_state.to_dict(),
            "agent_execution_state": self.agent_execution_state.to_dict(),
            "evidence_pool": {k: v.to_dict() for k, v in self.evidence_pool.items()},
            "graph_nodes": {k: v.to_dict() for k, v in self.graph_nodes.items()},
            "graph_edges": [e.to_dict() for e in self.graph_edges],
            "contradictions": [c.to_dict() for c in self.contradictions]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CanonicalProjectState":
        ev_pool = {
            k: Evidence.from_dict(v) for k, v in data.get("evidence_pool", {}).items()
        }
        g_nodes = {
            k: GraphNode.from_dict(v) for k, v in data.get("graph_nodes", {}).items()
        }
        g_edges = [
            GraphEdge.from_dict(e) for e in data.get("graph_edges", [])
        ]
        contradictions = [
            ContradictionRecord.from_dict(c) for c in data.get("contradictions", [])
        ]

        return cls(
            schema_version=data.get("schema_version", "1.0.0"),
            project_id=data.get("project_id", f"proj_{uuid.uuid4().hex[:8]}"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            project_state=ProjectState.from_dict(data.get("project_state", {})),
            conversational_state=ConversationalState.from_dict(data.get("conversational_state", {})),
            agent_execution_state=AgentExecutionState.from_dict(data.get("agent_execution_state", {})),
            evidence_pool=ev_pool,
            graph_nodes=g_nodes,
            graph_edges=g_edges,
            contradictions=contradictions
        )


# ==============================================================================
# 4. HANDOFF CHECKPOINT & MULTI-TURN CHAIN OF CUSTODY (Phase 45)
# ==============================================================================

@dataclass
class HandoffCheckpoint:
    """Represents an immutable checkpoint in a multi-model conversational chain."""
    checkpoint_id: str
    origin_model: str
    target_model: str
    timestamp: str
    prompt_summary: str
    compressed_prompt: str
    total_messages: int
    total_code_blocks: int
    parent_checkpoint_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HandoffCheckpoint":
        return cls(**data)


class HandoffCheckpointManager:
    """Manages persistent checkpoint trails in .continuum/handoffs/."""

    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root).resolve()
        self.handoffs_dir = self.workspace_root / ".continuum" / "handoffs"

    def initialize(self) -> None:
        self.handoffs_dir.mkdir(parents=True, exist_ok=True)

    def record_checkpoint(self, checkpoint: HandoffCheckpoint) -> Path:
        self.initialize()
        file_path = self.handoffs_dir / f"checkpoint_{checkpoint.checkpoint_id}.json"
        import json
        file_path.write_text(json.dumps(checkpoint.to_dict(), indent=2), encoding="utf-8")
        return file_path

    def list_checkpoints(self) -> List[HandoffCheckpoint]:
        if not self.handoffs_dir.is_dir():
            return []
        import json
        checkpoints = []
        for p in sorted(self.handoffs_dir.glob("checkpoint_*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                checkpoints.append(HandoffCheckpoint.from_dict(data))
            except Exception:
                continue
        return checkpoints

    def get_checkpoint(self, checkpoint_id: str) -> Optional[HandoffCheckpoint]:
        file_path = self.handoffs_dir / f"checkpoint_{checkpoint_id}.json"
        if not file_path.is_file():
            return None
        import json
        data = json.loads(file_path.read_text(encoding="utf-8"))
        return HandoffCheckpoint.from_dict(data)

    def get_lineage(self, checkpoint_id: str) -> List[HandoffCheckpoint]:
        """Traverses the parent chain back to the root, returning chronological lineage."""
        lineage: List[HandoffCheckpoint] = []
        curr_id: Optional[str] = checkpoint_id
        visited = set()

        while curr_id and curr_id not in visited:
            visited.add(curr_id)
            cp = self.get_checkpoint(curr_id)
            if not cp:
                break
            lineage.append(cp)
            curr_id = cp.parent_checkpoint_id

        lineage.reverse()
        return lineage


