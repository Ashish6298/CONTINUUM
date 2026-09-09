"""
Tests for Schema Validation, JSON Round-Trip Serialization, and File Persistence.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from core.enums import Status, EvidenceType, EvidenceLevel, NodeType, RelationType
from core.evidence import Evidence, EvidenceProvenance
from core.state_models import (
    CanonicalProjectState,
    ProjectState,
    ConversationalState,
    AgentExecutionState,
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
    GraphEdge
)
from core.schema import get_canonical_project_state_schema, validate_canonical_state_dict
from core.serializer import (
    CanonicalStateSerializer,
    StateSerializationError,
    StateValidationError
)


class TestSerialization(unittest.TestCase):

    def setUp(self):
        self.state = CanonicalProjectState(
            project_id="proj_integration_test",
            schema_version="1.0.0",
            project_state=ProjectState(
                root_path="d:/CONTINUUM",
                detected_languages=["python"],
                files=["d:/CONTINUUM/continuum/core/enums.py"],
                manifests=[
                    ManifestInfo(
                        manifest_type="pyproject.toml",
                        file_path="d:/CONTINUUM/pyproject.toml",
                        project_name="continuum-ai",
                        version="0.1.0",
                        dependencies={},
                        dev_dependencies={"pytest": ">=7.0.0"},
                        scripts={}
                    )
                ],
                symbols=[
                    AstSymbol(
                        name="Status",
                        kind="class",
                        file_path="d:/CONTINUUM/continuum/core/enums.py",
                        line_start=8,
                        line_end=25,
                        exported=True,
                        docstring="Standard status system"
                    )
                ],
                git_state=GitState(
                    is_repo=True,
                    branch="main",
                    head_commit="abc1234",
                    is_dirty=False
                ),
                test_results=[
                    TestResult(
                        test_id="test_001",
                        name="test_enums",
                        suite="core",
                        status=Status.VERIFIED,
                        exit_code=0,
                        duration_ms=15.2
                    )
                ],
                build_status=Status.VERIFIED
            ),
            conversational_state=ConversationalState(
                session_id="session_456",
                user_requirements=[
                    Requirement(
                        id="req_001",
                        title="Decouple physical ground truth from chat",
                        description="Physical state must remain segregated from agent claims.",
                        status=Status.VERIFIED
                    )
                ],
                architectural_decisions=[
                    ArchitecturalDecision(
                        id="arch_001",
                        title="Hierarchy of Evidence arbitration",
                        rationale="Runtime and tests have level 1 seniority; chat claims are level 5.",
                        constraints=["No blind LLM claim adoption"]
                    )
                ]
            ),
            agent_execution_state=AgentExecutionState(
                agent_id="agent_continuum",
                model_name="claude-3-5-sonnet",
                active_tasks=[
                    TacticalTask(
                        id="task_001",
                        title="Implement Phase 0",
                        status=Status.IN_PROGRESS,
                        target_files=["d:/CONTINUUM/continuum/core/state_models.py"]
                    )
                ]
            )
        )

        # Add evidence
        ev = Evidence(
            type=EvidenceType.TEST_RUN,
            summary="All unit tests passed",
            raw_payload={"suite": "core", "passed": 1, "failed": 0},
            provenance=EvidenceProvenance(
                extractor_name="PyTestExtractor",
                source_uri="tests/test_enums_and_evidence.py",
                locator="TestEnumsAndEvidence"
            )
        )
        self.state.add_evidence(ev)

        # Add graph node and edge
        node1 = GraphNode(id="node_milestone_1", name="Milestone 1", node_type=NodeType.MILESTONE, status=Status.IN_PROGRESS, confidence_score=85.0)
        node2 = GraphNode(id="node_phase_0", name="Phase 0", node_type=NodeType.PHASE, status=Status.VERIFIED, confidence_score=100.0, evidence_ids=[ev.id])
        self.state.graph_nodes[node1.id] = node1
        self.state.graph_nodes[node2.id] = node2
        self.state.graph_edges.append(GraphEdge(source_id=node1.id, target_id=node2.id, relation=RelationType.DEPENDS_ON))

    def test_schema_generator_structure(self):
        schema = get_canonical_project_state_schema()
        self.assertEqual(schema["title"], "CanonicalProjectState")
        self.assertIn("project_state", schema["required"])
        self.assertIn("conversational_state", schema["required"])
        self.assertIn("agent_execution_state", schema["required"])

    def test_roundtrip_dict_and_json(self):
        # Serialize to dict and json
        data_dict = CanonicalStateSerializer.to_dict(self.state)
        json_str = CanonicalStateSerializer.to_json(self.state)

        # Deserialize back
        from_dict_obj = CanonicalStateSerializer.from_dict(data_dict)
        from_json_obj = CanonicalStateSerializer.from_json(json_str)

        self.assertEqual(from_dict_obj.project_id, self.state.project_id)
        self.assertEqual(from_json_obj.project_id, self.state.project_id)
        self.assertEqual(len(from_json_obj.project_state.symbols), 1)
        self.assertEqual(from_json_obj.project_state.symbols[0].name, "Status")
        self.assertEqual(len(from_json_obj.evidence_pool), 1)
        self.assertEqual(len(from_json_obj.graph_nodes), 2)
        self.assertEqual(len(from_json_obj.graph_edges), 1)

    def test_schema_validation_rejects_corrupted_data(self):
        corrupted_dict = CanonicalStateSerializer.to_dict(self.state)
        
        # Corrupt test_result status with invalid string
        corrupted_dict["project_state"]["test_results"][0]["status"] = "SUPER_PASSED"
        is_valid, errors = validate_canonical_state_dict(corrupted_dict)
        self.assertFalse(is_valid)
        self.assertTrue(any("Invalid TestResult status" in e for e in errors))

        # Expect StateValidationError when trying to deserialize
        with self.assertRaises(StateValidationError):
            CanonicalStateSerializer.from_dict(corrupted_dict)

    def test_schema_validation_rejects_missing_top_level(self):
        incomplete_dict = {"schema_version": "1.0.0"}
        is_valid, errors = validate_canonical_state_dict(incomplete_dict)
        self.assertFalse(is_valid)
        self.assertTrue(len(errors) > 5)

    def test_file_persistence_atomic_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / ".continuum" / "project-state.json"
            
            CanonicalStateSerializer.save_to_file(self.state, file_path)
            self.assertTrue(file_path.exists())

            loaded_state = CanonicalStateSerializer.load_from_file(file_path)
            self.assertEqual(loaded_state.project_id, self.state.project_id)
            self.assertEqual(loaded_state.conversational_state.session_id, "session_456")


if __name__ == "__main__":
    unittest.main()
