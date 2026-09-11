"""
Project Continuum - End-to-End Orchestrator Pipeline
=====================================================
Milestone 8 - Phase 19: End-to-End Integration & Polyglot Validation.
Connects the complete Continuum pipeline:
1. Multi-source evidence harvesting (Workspace, Config, Git, Verification, Conversation).
2. Evidence Resolution Engine (arbitration by hierarchy level 1-5).
3. Contradiction Detection Engine (detecting mismatches between claims and reality).
4. Confidence Calculation Engine (explainable scoring grounded in proof).
5. Canonical State Graph / DAG (node/edge modeling, cycle prevention, dependency propagation).
6. Task-driven Context Selection & Budget Pruning (minimum sufficient high-signal context).
7. Model-Specific Handoff Adapters (Claude, Codex/GPT, Gemini, Local LLM, Universal).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from core.enums import EvidenceLevel, EvidenceType, NodeType, RelationType, Status, TargetModel
from core.evidence import Evidence
from core.state_models import (
    AgentClaim,
    AgentExecutionState,
    CanonicalProjectState,
    ContradictionRecord,
    ConversationalState,
    GraphEdge,
    GraphNode,
    ProjectState,
    Requirement,
    TestResult,
)
from core.serializer import CanonicalStateSerializer
from extractors.workspace_extractor import WorkspaceEvidenceExtractor
from extractors.config_extractor import ConfigEvidenceExtractor
from extractors.git_extractor import GitEvidenceExtractor
from extractors.verification_extractor import VerificationEvidenceExtractor
from extractors.conversation_extractor import ConversationEvidenceExtractor
from resolution.resolver import EvidenceResolver, ResolutionResult
from contradictions.detector import ContradictionDetector
from confidence.calculator import ConfidenceCalculator
from graph.manager import StateGraphManager
from context.selector import TaskContextSelector
from context.pruner import ContextPruner
from context.models import TaskContext
from handoff.packager import UniversalHandoffPackager
from handoff.adapters import get_adapter_for_model
from handoff.models import HandoffPackage


@dataclass
class PipelineExecutionSummary:
    """Summary metrics of an end-to-end pipeline execution."""
    project_id: str
    workspace_path: str
    languages_detected: List[str]
    total_files_scanned: int
    total_symbols_extracted: int
    total_evidence_collected: int
    contradictions_detected: int
    project_confidence: float
    graph_nodes_count: int
    graph_edges_count: int
    context_tokens_generated: Optional[int] = None
    handoff_formats_generated: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "workspace_path": self.workspace_path,
            "languages_detected": self.languages_detected,
            "total_files_scanned": self.total_files_scanned,
            "total_symbols_extracted": self.total_symbols_extracted,
            "total_evidence_collected": self.total_evidence_collected,
            "contradictions_detected": self.contradictions_detected,
            "project_confidence": self.project_confidence,
            "graph_nodes_count": self.graph_nodes_count,
            "graph_edges_count": self.graph_edges_count,
            "context_tokens_generated": self.context_tokens_generated,
            "handoff_formats_generated": self.handoff_formats_generated,
        }


class ContinuumPipeline:
    """
    High-level orchestrator for Project Continuum.
    Executes the complete end-to-end pipeline from physical workspace scanning
    to model-optimized handoff generation.
    """

    def __init__(
        self,
        workspace_path: Union[str, Path],
        project_id: Optional[str] = None,
        custom_parsers: Optional[List[Any]] = None
    ):
        self.workspace_path = Path(workspace_path).resolve()
        self.project_id = project_id or f"proj_{self.workspace_path.name}"

        # Initialize subsystem engines
        self.ws_extractor = WorkspaceEvidenceExtractor(custom_parsers=custom_parsers)
        self.config_extractor = ConfigEvidenceExtractor()
        self.git_extractor = GitEvidenceExtractor()
        self.verification_extractor = VerificationEvidenceExtractor()
        self.conversation_extractor = ConversationEvidenceExtractor()

        self.resolver = EvidenceResolver()
        self.contradiction_detector = ContradictionDetector()
        self.confidence_calculator = ConfidenceCalculator()
        self.context_selector = TaskContextSelector()
        self.context_pruner = ContextPruner()
        self.universal_packager = UniversalHandoffPackager()

    def run_full_analysis(
        self,
        conversation_input: Optional[Union[str, Path, Dict[str, Any]]] = None,
        explicit_verification_results: Optional[List[TestResult]] = None,
        task_description: Optional[str] = None,
        token_budget: Optional[int] = None,
        target_models: Optional[List[TargetModel]] = None
    ) -> Tuple[CanonicalProjectState, PipelineExecutionSummary, Dict[str, Any]]:
        """
        Executes the complete end-to-end pipeline:
        1. Workspace scanning & symbol parsing.
        2. Manifest & config discovery.
        3. Git tree inspection.
        4. Test verification & results recording.
        5. Conversation ingestion (preserving strict 3-state separation).
        6. Truth resolution across evidence hierarchy.
        7. Contradiction detection.
        8. Grounded confidence computation.
        9. DAG construction & dependency propagation.
        10. Task-driven context selection & budget pruning.
        11. Universal & model-specific handoff generation.
        """
        # Initialize Canonical State container
        canonical_state = CanonicalProjectState(
            schema_version="1.0.0",
            project_id=self.project_id,
            project_state=ProjectState(root_path=str(self.workspace_path))
        )

        # ----------------------------------------------------------------------
        # Step 1: Physical Workspace & Source Code Evidence Extraction
        # ----------------------------------------------------------------------
        self.ws_extractor.populate_project_state(str(self.workspace_path), canonical_state)

        # ----------------------------------------------------------------------
        # Step 2: Configuration, Environment & Manifest Extraction
        # ----------------------------------------------------------------------
        self.config_extractor.populate_project_state(str(self.workspace_path), canonical_state)

        # ----------------------------------------------------------------------
        # Step 3: Git History & Delta Analysis
        # ----------------------------------------------------------------------
        self.git_extractor.populate_project_state(str(self.workspace_path), canonical_state)

        # ----------------------------------------------------------------------
        # Step 4: Verification & Test Execution Recording
        # ----------------------------------------------------------------------
        if explicit_verification_results:
            for tr in explicit_verification_results:
                canonical_state.project_state.test_results.append(tr)
                test_ev = self.verification_extractor.create_evidence(
                    evidence_type=EvidenceType.TEST_RUN,
                    summary=f"Test Suite: {tr.suite} (Test: {tr.name}, Status: {tr.status.value})",
                    raw_payload=tr.to_dict(),
                    source_uri=tr.suite,
                    locator=f"test:{tr.suite}:{tr.name}"
                )
                canonical_state.add_evidence(test_ev)

        # ----------------------------------------------------------------------
        # Step 5: Conversation & Agent State Ingestion (Strict 3-State Separation)
        # ----------------------------------------------------------------------
        if conversation_input:
            self.conversation_extractor.ingest_transcript(conversation_input, canonical_state)

        # ----------------------------------------------------------------------
        # Step 6 & 7: Contradiction Detection & Discrepancy Resolution
        # ----------------------------------------------------------------------
        contradictions = self.contradiction_detector.detect_contradictions(
            project_state=canonical_state.project_state,
            conversational_state=canonical_state.conversational_state,
            evidence_pool=canonical_state.evidence_pool
        )
        canonical_state.contradictions = contradictions

        # ----------------------------------------------------------------------
        # Step 8 & 9: Canonical State Graph (DAG) Construction
        # ----------------------------------------------------------------------
        graph_manager = StateGraphManager(canonical_state)
        graph_manager.build_from_canonical_state(canonical_state)

        # ----------------------------------------------------------------------
        # Step 10: Grounded Confidence Calculation
        # ----------------------------------------------------------------------
        proj_confidence, conf_explanation = self.confidence_calculator.calculate_project_confidence(canonical_state)

        # ----------------------------------------------------------------------
        # Step 11: Task Context Selection & Budget Pruning (Optional)
        # ----------------------------------------------------------------------
        task_ctx: Optional[TaskContext] = None
        pruned_tokens = None
        if task_description:
            task_ctx = self.context_selector.extract_task_context(
                task_description=task_description,
                canonical_state=canonical_state,
                token_budget=token_budget
            )
            if token_budget:
                prune_res = self.context_pruner.prune_to_budget(task_ctx, token_budget)
                pruned_tokens = prune_res.estimated_tokens_after

        # ----------------------------------------------------------------------
        # Step 12: Model Handoff Generation (Universal & Model-Specific)
        # ----------------------------------------------------------------------
        handoff_results: Dict[str, Any] = {}
        generated_formats: List[str] = []

        # Universal Handoff Package
        universal_pkg = self.universal_packager.generate_package(canonical_state, task_ctx)
        handoff_results["universal"] = universal_pkg
        generated_formats.append("universal")

        # Model-Specific Adapters
        models_to_generate = target_models or [
            TargetModel.CLAUDE,
            TargetModel.CODEX_GPT,
            TargetModel.GEMINI,
            TargetModel.LOCAL_LLM
        ]

        for model in models_to_generate:
            adapter = get_adapter_for_model(model)
            model_handoff = adapter.generate_handoff(canonical_state)
            handoff_results[model.value] = model_handoff
            handoff_results[model.value.lower()] = model_handoff
            if model == TargetModel.CODEX_GPT:
                handoff_results["codex"] = model_handoff
            generated_formats.append(model.value)

        p_state = canonical_state.project_state
        # Build execution summary
        summary = PipelineExecutionSummary(
            project_id=self.project_id,
            workspace_path=str(self.workspace_path),
            languages_detected=list(set(p_state.detected_languages)),
            total_files_scanned=len(p_state.files),
            total_symbols_extracted=len(p_state.symbols),
            total_evidence_collected=len(canonical_state.evidence_pool),
            contradictions_detected=len(contradictions),
            project_confidence=proj_confidence,
            graph_nodes_count=len(canonical_state.graph_nodes),
            graph_edges_count=len(canonical_state.graph_edges),
            context_tokens_generated=pruned_tokens,
            handoff_formats_generated=generated_formats
        )

        return canonical_state, summary, handoff_results
