"""
Project Continuum — Phase 55 Test Suite
========================================
Milestone 36: Domain Model and Invariants
Phase 55: Invariant Matrix and Architecture Decision

Validates:
1. Complete mapping and registration of behavioral invariants I-01 through I-20.
2. Transaction and recovery boundary specifications for all critical operations.
3. User-safe error hierarchy, clean serialization, and secret isolation.
4. Architecture Decision Record (ADR-001) metadata, rationale, and repository evidence.
5. Invariant document integrity and report existence.
"""

import unittest
from pathlib import Path
from core.invariants import (
    InvariantId,
    InvariantCategory,
    InvariantDefinition,
    INVARIANT_REGISTRY,
    TransactionOperation,
    TransactionBoundary,
    TRANSACTION_BOUNDARIES,
    ContinuumUserError,
    InvariantViolationError,
    CommitFailedError,
    UnsafeRestoreError,
    ImportValidationError,
    RetentionLimitError,
    MigrationError,
    ArchitectureDecisionRecord,
    ADR_001,
    get_invariant,
    get_all_invariants,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestPhase55InvariantsAndADR(unittest.TestCase):
    """Test suite for Phase 55 Invariant Matrix and Architecture Decision Record."""

    def test_all_twenty_invariants_registered_and_mapped(self):
        """Verifies that all 20 invariants (I-01 to I-20) are registered with complete metadata."""
        all_invariants = get_all_invariants()
        self.assertEqual(len(all_invariants), 20)
        self.assertEqual(len(INVARIANT_REGISTRY), 20)

        for inv in all_invariants:
            self.assertIsInstance(inv.id, InvariantId)
            self.assertTrue(inv.title.strip())
            self.assertTrue(inv.description.strip())
            self.assertIsInstance(inv.category, InvariantCategory)
            self.assertTrue(inv.enforcement_mechanism.strip())
            self.assertTrue(inv.test_suite.strip())
            self.assertTrue(len(inv.test_cases) > 0)
            self.assertTrue(inv.is_active_phase)

            # Check serialization
            inv_dict = inv.to_dict()
            self.assertEqual(inv_dict["id"], inv.id.value)
            self.assertEqual(inv_dict["title"], inv.title)
            self.assertEqual(inv_dict["category"], inv.category.value)
            self.assertIsInstance(inv_dict["test_cases"], list)

    def test_invariant_retrieval_functions(self):
        """Verifies lookup of individual invariants and key error handling."""
        i_01 = get_invariant(InvariantId.I_01)
        self.assertEqual(i_01.id, InvariantId.I_01)
        self.assertIn("Stable", i_01.title)

        i_20 = get_invariant(InvariantId.I_20)
        self.assertEqual(i_20.id, InvariantId.I_20)
        self.assertIn("Verification", i_20.title)

        with self.assertRaises(KeyError):
            get_invariant("INVALID_INV")

    def test_transaction_boundaries_catalog_completeness(self):
        """Verifies all 6 transaction operations have defined boundaries and user-safe errors."""
        required_operations = {
            TransactionOperation.COMMIT,
            TransactionOperation.BRANCH,
            TransactionOperation.RESTORE,
            TransactionOperation.IMPORT,
            TransactionOperation.RETENTION,
            TransactionOperation.MIGRATION,
        }
        self.assertEqual(set(TRANSACTION_BOUNDARIES.keys()), required_operations)

        for op, boundary in TRANSACTION_BOUNDARIES.items():
            self.assertEqual(boundary.operation, op)
            self.assertTrue(boundary.atomicity_mechanism.strip())
            self.assertTrue(boundary.pre_condition.strip())
            self.assertTrue(boundary.failure_recovery.strip())
            self.assertTrue(boundary.audit_record_created)
            self.assertTrue(boundary.user_safe_error.strip())

            b_dict = boundary.to_dict()
            self.assertEqual(b_dict["operation"], op.value)
            self.assertIn("atomicity_mechanism", b_dict)

    def test_user_safe_error_hierarchy(self):
        """Verifies user-safe error base class and all specialized subclasses."""
        base_err = ContinuumUserError(
            user_message="An error occurred",
            suggested_action="Try again later",
            error_code="ERR_CUSTOM",
            internal_details="Secret key: sk-12345678",
            remediable=True,
        )
        self.assertEqual(str(base_err), "An error occurred")
        err_dict = base_err.to_dict()
        self.assertEqual(err_dict["error_code"], "ERR_CUSTOM")
        self.assertEqual(err_dict["message"], "An error occurred")
        self.assertEqual(err_dict["suggested_action"], "Try again later")
        self.assertTrue(err_dict["remediable"])
        # Ensure internal details (e.g. leaked secrets) are NOT included in user-facing dict
        self.assertNotIn("internal_details", err_dict)
        self.assertNotIn("sk-12345678", str(err_dict))

        # InvariantViolationError
        inv_err = InvariantViolationError(
            InvariantId.I_06,
            "Attempted to treat derived brief as authoritative ground truth",
        )
        self.assertIn("I-06", inv_err.user_message)
        self.assertEqual(inv_err.error_code, "ERR_INVARIANT_I_06")

        # CommitFailedError
        commit_err = CommitFailedError("Disk full")
        self.assertEqual(commit_err.error_code, "ERR_STORAGE_COMMIT_FAILED")

        # UnsafeRestoreError
        restore_err = UnsafeRestoreError("Target checkpoint corrupted")
        self.assertEqual(restore_err.error_code, "ERR_RESTORE_UNSAFE")

        # ImportValidationError
        import_err = ImportValidationError("Malformed JSON", ["Missing 'id'", "Invalid type"])
        self.assertEqual(import_err.error_code, "ERR_IMPORT_VALIDATION")
        self.assertEqual(len(import_err.validation_errors), 2)

        # RetentionLimitError
        retention_err = RetentionLimitError("Branch head cannot be pruned")
        self.assertEqual(retention_err.error_code, "ERR_RETENTION_ANCESTRY_GUARD")

        # MigrationError
        mig_err = MigrationError("Unsupported legacy schema v0.1")
        self.assertEqual(mig_err.error_code, "ERR_MIGRATION_FAILED")

    def test_adr_001_specification_and_evidence(self):
        """Verifies ADR-001 metadata, decision rationale, and repository evidence files."""
        self.assertEqual(ADR_001.id, "ADR-001")
        self.assertEqual(ADR_001.status, "ACCEPTED")
        self.assertIn("Hybrid Partitioned JSON", ADR_001.title)
        self.assertIn("sqlite3", ADR_001.persistence_boundary_choice)
        self.assertTrue(len(ADR_001.consequences_positive) >= 3)
        self.assertTrue(len(ADR_001.consequences_tradeoffs) >= 1)

        # Verify cited repository evidence files physically exist
        for evidence in ADR_001.repository_evidence:
            file_rel_path = evidence.split(":")[0].strip()
            evidence_path = REPO_ROOT / file_rel_path
            self.assertTrue(
                evidence_path.exists(),
                f"Referenced ADR evidence file does not exist: {evidence_path}",
            )

        adr_dict = ADR_001.to_dict()
        self.assertEqual(adr_dict["id"], "ADR-001")
        self.assertEqual(adr_dict["status"], "ACCEPTED")

    def test_adr_document_and_reports_integrity(self):
        """Verifies that docs/ADR_001_UNIVERSAL_RESUME_ARCHITECTURE.md exists and documents all 20 invariants."""
        adr_file = REPO_ROOT / "docs" / "ADR_001_UNIVERSAL_RESUME_ARCHITECTURE.md"
        self.assertTrue(adr_file.exists(), "ADR-001 markdown file missing from docs/")

        adr_content = adr_file.read_text(encoding="utf-8")
        for inv_id in InvariantId:
            self.assertIn(
                inv_id.value,
                adr_content,
                f"Invariant {inv_id.value} missing from ADR documentation",
            )

        # Check existing milestone reports
        reports_dir = REPO_ROOT / "docs" / "reports"
        self.assertTrue(reports_dir.exists())
        self.assertTrue((reports_dir / "PHASE_50_DISCOVERY_REPORT.txt").exists())
        self.assertTrue((reports_dir / "PHASE_51_DATA_PERSISTENCE_SECURITY_AUDIT.txt").exists())
        self.assertTrue((reports_dir / "PHASE_52_BASELINE_VERIFICATION_REPORT.txt").exists())
        self.assertTrue((reports_dir / "PHASE_53_ACTIVITY_MODEL_REPORT.txt").exists())
        self.assertTrue((reports_dir / "PHASE_54_CHECKPOINT_MODEL_REPORT.txt").exists())


if __name__ == "__main__":
    unittest.main()
