"""
Tests for Component Interfaces and Protocol Compliance.
"""

import unittest
from typing import Any, Dict, List, Optional, Tuple

from core.enums import Status, EvidenceType, TargetModel
from core.evidence import Evidence
from core.state_models import (
    CanonicalProjectState,
    ContradictionRecord,
    GraphNode,
    GraphEdge,
    ProjectState,
    ConversationalState,
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


class MockExtractor:
    @property
    def extractor_name(self) -> str:
        return "MockWorkspaceExtractor"

    @property
    def supported_evidence_types(self) -> List[EvidenceType]:
        return [EvidenceType.SOURCE_CODE, EvidenceType.AST_SYMBOL]

    def can_extract(self, target_path_or_input: str) -> bool:
        return target_path_or_input.endswith(".py")

    def extract(self, target_path_or_input: str, context: Optional[Dict[str, Any]] = None) -> List[Evidence]:
        return [Evidence(type=EvidenceType.SOURCE_CODE, summary=f"File {target_path_or_input}")]


class MockResolver:
    def resolve_status(
        self,
        target_id: str,
        evidence_list: List[Evidence],
        claims: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[Status, Optional[Evidence], str]:
        if not evidence_list:
            return Status.UNVERIFIED, None, "No physical evidence found"
        return Status.VERIFIED, evidence_list[0], "Verified by physical proof"


class MockContradictionDetector:
    def detect_contradictions(
        self,
        project_state: ProjectState,
        conversational_state: ConversationalState,
        evidence_pool: Dict[str, Evidence]
    ) -> List[ContradictionRecord]:
        return []


class MockConfidenceCalculator:
    def calculate_node_confidence(
        self,
        node: GraphNode,
        evidence_pool: Dict[str, Evidence],
        contradictions: List[ContradictionRecord]
    ) -> Tuple[float, Dict[str, Any]]:
        return 100.0, {"basis": "mock"}

    def calculate_project_confidence(
        self,
        canonical_state: CanonicalProjectState
    ) -> Tuple[float, Dict[str, Any]]:
        return 100.0, {"basis": "mock"}


class MockGraphManager:
    def __init__(self):
        self.nodes = {}
        self.edges = []

    def add_node(self, node: GraphNode) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: GraphEdge) -> None:
        self.edges.append(edge)

    def get_dependencies(self, node_id: str, recursive: bool = False) -> List[GraphNode]:
        return []

    def get_dependents(self, node_id: str, recursive: bool = False) -> List[GraphNode]:
        return []

    def detect_cycles(self) -> List[List[str]]:
        return []

    def propagate_invalidation(self, changed_node_id: str) -> List[str]:
        return []

    def export_mermaid(self) -> str:
        return "graph TD"


class MockContextSelector:
    def select_context_for_task(
        self,
        task_description: str,
        canonical_state: CanonicalProjectState,
        token_budget: Optional[int] = None
    ) -> Dict[str, Any]:
        return {"task": task_description, "selected_nodes": []}


class MockClaudeAdapter:
    @property
    def target_model(self) -> TargetModel:
        return TargetModel.CLAUDE

    def generate_handoff(
        self,
        canonical_state: CanonicalProjectState,
        context_selection: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        return {
            "handoff.md": "# Claude Handoff",
            "project-context.md": "<context></context>",
            "project-state.json": "{}"
        }


class TestInterfaces(unittest.TestCase):

    def test_mock_extractor_protocol_compliance(self):
        extractor = MockExtractor()
        self.assertIsInstance(extractor, IEvidenceExtractor)
        self.assertTrue(extractor.can_extract("test.py"))
        self.assertFalse(extractor.can_extract("test.js"))

    def test_mock_resolver_protocol_compliance(self):
        resolver = MockResolver()
        self.assertIsInstance(resolver, IEvidenceResolver)

    def test_mock_contradiction_detector_protocol_compliance(self):
        detector = MockContradictionDetector()
        self.assertIsInstance(detector, IContradictionDetector)

    def test_mock_confidence_calculator_protocol_compliance(self):
        calc = MockConfidenceCalculator()
        self.assertIsInstance(calc, IConfidenceCalculator)

    def test_mock_graph_manager_protocol_compliance(self):
        mgr = MockGraphManager()
        self.assertIsInstance(mgr, IStateGraphManager)

    def test_mock_context_selector_protocol_compliance(self):
        selector = MockContextSelector()
        self.assertIsInstance(selector, IContextSelector)

    def test_mock_model_adapter_protocol_compliance(self):
        adapter = MockClaudeAdapter()
        self.assertIsInstance(adapter, IModelAdapter)
        self.assertEqual(adapter.target_model, TargetModel.CLAUDE)


if __name__ == "__main__":
    unittest.main()
