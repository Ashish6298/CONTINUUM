"""
Tests for Canonical Enums, Evidence Model, and Provenance Integrity.
"""

import unittest
from datetime import datetime, timezone

from core.enums import (
    Status,
    EvidenceType,
    EvidenceLevel,
    NodeType,
    RelationType,
    TargetModel
)
from core.evidence import Evidence, EvidenceProvenance


class TestEnumsAndEvidence(unittest.TestCase):

    def test_status_helpers(self):
        self.assertTrue(Status.is_terminal_success(Status.VERIFIED))
        self.assertFalse(Status.is_terminal_success(Status.IN_PROGRESS))
        self.assertFalse(Status.is_terminal_success(Status.FAILED))
        
        self.assertTrue(Status.is_actionable(Status.PENDING))
        self.assertTrue(Status.is_actionable(Status.BLOCKED))
        self.assertTrue(Status.is_actionable(Status.FAILED))
        self.assertFalse(Status.is_actionable(Status.VERIFIED))

    def test_evidence_hierarchy_level_mapping(self):
        self.assertEqual(
            EvidenceLevel.get_level_for_type(EvidenceType.TEST_RUN),
            EvidenceLevel.LEVEL_1_RUNTIME_TEST
        )
        self.assertEqual(
            EvidenceLevel.get_level_for_type(EvidenceType.SOURCE_CODE),
            EvidenceLevel.LEVEL_2_CODE_AST
        )
        self.assertEqual(
            EvidenceLevel.get_level_for_type(EvidenceType.AST_SYMBOL),
            EvidenceLevel.LEVEL_2_CODE_AST
        )
        self.assertEqual(
            EvidenceLevel.get_level_for_type(EvidenceType.GIT_COMMIT),
            EvidenceLevel.LEVEL_3_GIT_STATE
        )
        self.assertEqual(
            EvidenceLevel.get_level_for_type(EvidenceType.DOCUMENTATION),
            EvidenceLevel.LEVEL_4_DOCUMENTATION
        )
        self.assertEqual(
            EvidenceLevel.get_level_for_type(EvidenceType.CONVERSATION_ASSERTION),
            EvidenceLevel.LEVEL_5_CONVERSATION
        )
        self.assertEqual(
            EvidenceLevel.get_level_for_type(EvidenceType.AGENT_CLAIM),
            EvidenceLevel.LEVEL_5_CONVERSATION
        )

    def test_evidence_hierarchy_seniority(self):
        # Level 1 should be strictly higher priority (lower integer) than Level 2, etc.
        self.assertLess(EvidenceLevel.LEVEL_1_RUNTIME_TEST, EvidenceLevel.LEVEL_2_CODE_AST)
        self.assertLess(EvidenceLevel.LEVEL_2_CODE_AST, EvidenceLevel.LEVEL_3_GIT_STATE)
        self.assertLess(EvidenceLevel.LEVEL_3_GIT_STATE, EvidenceLevel.LEVEL_4_DOCUMENTATION)
        self.assertLess(EvidenceLevel.LEVEL_4_DOCUMENTATION, EvidenceLevel.LEVEL_5_CONVERSATION)

    def test_evidence_creation_and_checksum_integrity(self):
        prov = EvidenceProvenance(
            extractor_name="WorkspaceAstExtractor",
            source_uri="src/auth/jwt.py",
            locator="symbol:verify_token#L45-L60"
        )
        ev = Evidence(
            type=EvidenceType.AST_SYMBOL,
            summary="Function signature verify_token(token: str) -> bool found",
            raw_payload={"name": "verify_token", "return_type": "bool", "params": ["token"]},
            provenance=prov
        )

        self.assertTrue(ev.id.startswith("ev_"))
        self.assertEqual(ev.level, EvidenceLevel.LEVEL_2_CODE_AST)
        self.assertTrue(ev.verify_integrity())
        self.assertTrue(len(ev.checksum) == 64)  # SHA-256

        # Tampering with raw payload should break integrity
        ev.raw_payload["hacked"] = True
        self.assertFalse(ev.verify_integrity())

    def test_evidence_serde(self):
        prov = EvidenceProvenance(
            extractor_name="TestRunnerExtractor",
            source_uri="tests/test_auth.py",
            locator="test_jwt_expiration"
        )
        ev = Evidence(
            type=EvidenceType.TEST_RUN,
            summary="Test test_jwt_expiration passed with exit code 0",
            raw_payload={"exit_code": 0, "duration_ms": 42.5},
            provenance=prov
        )
        data = ev.to_dict()
        restored = Evidence.from_dict(data)

        self.assertEqual(ev.id, restored.id)
        self.assertEqual(ev.type, restored.type)
        self.assertEqual(ev.level, restored.level)
        self.assertEqual(ev.summary, restored.summary)
        self.assertEqual(ev.checksum, restored.checksum)
        self.assertEqual(restored.provenance.extractor_name, "TestRunnerExtractor")


if __name__ == "__main__":
    unittest.main()
