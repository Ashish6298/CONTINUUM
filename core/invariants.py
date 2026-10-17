"""
Project Continuum — Architectural Invariants, Transaction Boundaries & ADR Registry
===================================================================================
Milestone 36: Domain Model and Invariants (Phase 55)

Formalizes:
1. Invariants I-01 through I-20 with requirement mappings, enforcement mechanisms,
   and designated test suites.
2. Transaction & Recovery Boundaries for commits, branching, restore, import,
   retention, and versioned migration.
3. User-safe error hierarchy providing actionable guidance without leaking secrets.
4. Architecture Decision Record (ADR-001) for the v1.4.0 Universal Resume Anywhere engine.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


class InvariantId(str, Enum):
    """Authoritative Invariant Identifiers defined in projectv1.4.0.txt."""
    I_01 = "I-01"
    I_02 = "I-02"
    I_03 = "I-03"
    I_04 = "I-04"
    I_05 = "I-05"
    I_06 = "I-06"
    I_07 = "I-07"
    I_08 = "I-08"
    I_09 = "I-09"
    I_10 = "I-10"
    I_11 = "I-11"
    I_12 = "I-12"
    I_13 = "I-13"
    I_14 = "I-14"
    I_15 = "I-15"
    I_16 = "I-16"
    I_17 = "I-17"
    I_18 = "I-18"
    I_19 = "I-19"
    I_20 = "I-20"


class InvariantCategory(str, Enum):
    """Categorization of behavioral invariants."""
    IDENTITY_AND_LIFECYCLE = "Identity & Lifecycle"
    DURABILITY_AND_TRANSACTION = "Durability & Transaction"
    SECURITY_AND_PRIVACY = "Security & Privacy"
    DATA_INTEGRITY_AND_RECOVERY = "Data Integrity & Recovery"
    SCALE_AND_PERFORMANCE = "Scale & Performance"
    ENGINEERING_VERIFICATION = "Engineering Verification"


@dataclass(frozen=True)
class InvariantDefinition:
    """Formal definition and test mapping for an architectural invariant."""
    id: InvariantId
    title: str
    description: str
    category: InvariantCategory
    enforcement_mechanism: str
    test_suite: str
    test_cases: List[str]
    is_active_phase: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id.value,
            "title": self.title,
            "description": self.description,
            "category": self.category.value,
            "enforcement_mechanism": self.enforcement_mechanism,
            "test_suite": self.test_suite,
            "test_cases": list(self.test_cases),
            "is_active_phase": self.is_active_phase,
        }


# ==============================================================================
# INVARIANTS I-01 THROUGH I-20 MAPPING
# ==============================================================================

INVARIANT_REGISTRY: Dict[InvariantId, InvariantDefinition] = {
    InvariantId.I_01: InvariantDefinition(
        id=InvariantId.I_01,
        title="Stable Activity & Checkpoint IDs",
        description="Activity and checkpoint IDs are permanent and immutable across edits, renames, and migrations.",
        category=InvariantCategory.IDENTITY_AND_LIFECYCLE,
        enforcement_mechanism="UUIDv4 generation with act_/chk_ prefixes; frozen IDs during mutation; validate_id assertions.",
        test_suite="tests/test_phase53_activity.py, tests/test_phase54_checkpoint.py",
        test_cases=[
            "test_activity_stable_id_on_rename_and_edit",
            "test_checkpoint_ancestry_and_provenance_immutability",
        ],
    ),
    InvariantId.I_02: InvariantDefinition(
        id=InvariantId.I_02,
        title="Durable Checkpoint Commit Confirmation",
        description="Successful checkpoint commit guarantees authoritative persistence on disk; success is never reported prematurely.",
        category=InvariantCategory.DURABILITY_AND_TRANSACTION,
        enforcement_mechanism="Two-phase atomic write (.tmp -> replace); synchronous flush before confirmation return.",
        test_suite="tests/test_phase51_audit.py, tests/test_phase56_persistence.py",
        test_cases=[
            "test_atomic_file_persistence_and_snapshots",
            "test_durable_commit_confirmation_and_failure",
        ],
    ),
    InvariantId.I_03: InvariantDefinition(
        id=InvariantId.I_03,
        title="Read-Only Historical Views",
        description="Viewing historical checkpoints is strictly read-only; browsing past states cannot silently rewrite history.",
        category=InvariantCategory.DATA_INTEGRITY_AND_RECOVERY,
        enforcement_mechanism="Defensive copy on retrieval; write prevention on historical timeline records; explicit restore boundary.",
        test_suite="tests/test_phase54_checkpoint.py, tests/test_phase63_timeline.py",
        test_cases=[
            "test_checkpoint_ancestry_and_provenance_immutability",
            "test_historical_checkpoint_view_is_immutable",
        ],
    ),
    InvariantId.I_04: InvariantDefinition(
        id=InvariantId.I_04,
        title="Non-Destructive Branch Continuation",
        description="Branching creates a new independent continuation with provenance ancestry, leaving original timeline intact.",
        category=InvariantCategory.IDENTITY_AND_LIFECYCLE,
        enforcement_mechanism="Creation of new activity/checkpoint tree linked via parent_checkpoint_id; zero mutation of origin timeline.",
        test_suite="tests/test_phase54_checkpoint.py, tests/test_phase65_branch.py",
        test_cases=[
            "test_checkpoint_ancestry_and_provenance_immutability",
            "test_branch_creates_independent_continuation",
        ],
    ),
    InvariantId.I_05: InvariantDefinition(
        id=InvariantId.I_05,
        title="Explicit & Recoverable State Restore",
        description="Restore explicitly changes working state, validates compatibility, preserves newer checkpoints, and is crash-safe.",
        category=InvariantCategory.DATA_INTEGRITY_AND_RECOVERY,
        enforcement_mechanism="Pre-restore safety snapshot; RESTORE audit checkpoint; no deletion of forward checkpoints.",
        test_suite="tests/test_phase51_audit.py, tests/test_phase66_restore.py",
        test_cases=[
            "test_state_corruption_detection_and_auto_recovery",
            "test_restore_preserves_forward_checkpoints",
        ],
    ),
    InvariantId.I_06: InvariantDefinition(
        id=InvariantId.I_06,
        title="Derived Briefs & Indexes are Non-Authoritative",
        description="Summaries, briefs, and search indexes are derived; authoritative ground truth resides solely in structured records.",
        category=InvariantCategory.DATA_INTEGRITY_AND_RECOVERY,
        enforcement_mechanism="Structured checkpoint fields marked authoritative; ResumeBrief has is_authoritative=False; index rebuild utility.",
        test_suite="tests/test_phase54_checkpoint.py, tests/test_phase60_briefs.py, tests/test_phase56_persistence.py",
        test_cases=[
            "test_authoritative_vs_derived_fields_isolation",
            "test_derived_brief_generation_from_authoritative_state",
        ],
    ),
    InvariantId.I_07: InvariantDefinition(
        id=InvariantId.I_07,
        title="Privacy-Preserving Search & Indexes",
        description="Search snippets and index construction strictly enforce capture settings and secret redaction during builds and rebuilds.",
        category=InvariantCategory.SECURITY_AND_PRIVACY,
        enforcement_mechanism="Credential sanitization and regex pattern masking applied prior to indexing and excerpt generation.",
        test_suite="tests/test_phase51_audit.py, tests/test_phase68_search_index.py",
        test_cases=[
            "test_secret_redaction_and_path_normalization",
            "test_search_index_excludes_redacted_secrets",
        ],
    ),
    InvariantId.I_08: InvariantDefinition(
        id=InvariantId.I_08,
        title="Opt-In & Bounded Automation",
        description="Automated capture and background indexing are opt-in, debounced, deduplicated, observable, and strictly bounded.",
        category=InvariantCategory.SCALE_AND_PERFORMANCE,
        enforcement_mechanism="Explicit auto_capture flag in configuration; deduplication hash checks; bounded queue sizes.",
        test_suite="tests/test_verification_extractor.py, tests/test_phase71_triggers.py",
        test_cases=[
            "test_discovery_does_not_execute_automatically",
            "test_automation_debouncing_and_deduplication",
        ],
    ),
    InvariantId.I_09: InvariantDefinition(
        id=InvariantId.I_09,
        title="Explicit Disclosure for External AI Services",
        description="No activity content or workspace code is transmitted to external AI endpoints without explicit user consent.",
        category=InvariantCategory.SECURITY_AND_PRIVACY,
        enforcement_mechanism="Zero network calls in default engine; loopback-only binding; explicit consent gate for external endpoints.",
        test_suite="tests/test_phase51_audit.py, tests/test_state_isolation.py",
        test_cases=[
            "test_loopback_host_security_enforcement",
            "test_cors_origin_whitelist_boundaries",
        ],
    ),
    InvariantId.I_10: InvariantDefinition(
        id=InvariantId.I_10,
        title="Comprehensive Secret Redaction",
        description="Secrets, API tokens, and private keys never enter briefs, logs, indexes, exports, or integration payloads.",
        category=InvariantCategory.SECURITY_AND_PRIVACY,
        enforcement_mechanism="SecretSanitizer with 10+ entropy and regex matchers; exclusion of sensitive files (.env, *.key).",
        test_suite="tests/test_phase51_audit.py, tests/test_server_api.py",
        test_cases=[
            "test_secret_redaction_and_path_normalization",
            "test_sanitize_workspace_diff",
        ],
    ),
    InvariantId.I_11: InvariantDefinition(
        id=InvariantId.I_11,
        title="Guarded Ancestry & Safe Retention",
        description="Never silently prune protected or required checkpoint ancestry; explain when retention limits cannot be met safely.",
        category=InvariantCategory.DATA_INTEGRITY_AND_RECOVERY,
        enforcement_mechanism="Ancestry graph traversal; protection markers on branch heads and milestones; RetentionLimitError explanation.",
        test_suite="tests/test_phase58_consistency.py, tests/test_phase73_retention.py",
        test_cases=[
            "test_retention_pruning_respects_protected_ancestry",
            "test_retention_error_on_impossible_constraint",
        ],
    ),
    InvariantId.I_12: InvariantDefinition(
        id=InvariantId.I_12,
        title="Pre-Write Import Validation",
        description="Validate imported packages, archives, or external checkpoints before mutating live storage.",
        category=InvariantCategory.DATA_INTEGRITY_AND_RECOVERY,
        enforcement_mechanism="Draft 2020-12 schema validation and relational foreign-key check in memory before disk write.",
        test_suite="tests/test_phase51_audit.py, tests/test_phase78_import.py",
        test_cases=[
            "test_schema_validation_and_rejection",
            "test_malformed_import_rejected_without_state_mutation",
        ],
    ),
    InvariantId.I_13: InvariantDefinition(
        id=InvariantId.I_13,
        title="Self-Contained Backup Scopes",
        description="Backups contain all necessary data, relationships, and metadata needed for their stated recovery scope.",
        category=InvariantCategory.DATA_INTEGRITY_AND_RECOVERY,
        enforcement_mechanism="Manifest-driven backup archiver validating completeness of referenced activities and checkpoints.",
        test_suite="tests/test_phase51_audit.py, tests/test_phase77_backup.py",
        test_cases=[
            "test_checkpoint_record_migration_compatibility",
            "test_backup_archive_completeness_and_restoration",
        ],
    ),
    InvariantId.I_14: InvariantDefinition(
        id=InvariantId.I_14,
        title="Idempotent & Recoverable Migration",
        description="Data migrations are schema-validated, recoverable via pre-migration snapshots, idempotent on replay, and truthful.",
        category=InvariantCategory.DATA_INTEGRITY_AND_RECOVERY,
        enforcement_mechanism="Migration version registry; dry-run preview capability; pre-migration backup; idempotent transform steps.",
        test_suite="tests/test_phase54_checkpoint.py, tests/test_phase57_migration.py",
        test_cases=[
            "test_legacy_handoff_checkpoint_migration_compatibility",
            "test_migration_idempotence_and_replay_safety",
        ],
    ),
    InvariantId.I_15: InvariantDefinition(
        id=InvariantId.I_15,
        title="Adapter Invariant Enforcement",
        description="External model adapters and integrations cannot bypass core validation, security rules, or domain invariants.",
        category=InvariantCategory.SECURITY_AND_PRIVACY,
        enforcement_mechanism="Adapters consume validated domain entities; adapter outputs pass through standard serializer/sanitizer.",
        test_suite="tests/test_phase51_audit.py, tests/test_phase72_adapters.py",
        test_cases=[
            "test_omni_model_adapters_contract",
            "test_checkpoint_validation_rules",
        ],
    ),
    InvariantId.I_16: InvariantDefinition(
        id=InvariantId.I_16,
        title="Lifecycle History & Valid Transitions",
        description="Lifecycle status transitions enforce explicit state machine rules, preserve history, and reject invalid transitions.",
        category=InvariantCategory.IDENTITY_AND_LIFECYCLE,
        enforcement_mechanism="VALID_STATUS_TRANSITIONS matrix in Activity; InvalidStatusTransitionError with valid options in message.",
        test_suite="tests/test_phase53_activity.py",
        test_cases=[
            "test_activity_valid_lifecycle_transitions",
            "test_activity_invalid_status_transition_rejected",
            "test_activity_reopen_completed_and_archive_recovery",
        ],
    ),
    InvariantId.I_17: InvariantDefinition(
        id=InvariantId.I_17,
        title="Bounded Retrieval & Streaming",
        description="Large histories, searches, and artifact listings enforce bounded memory retrieval, pagination, or streaming.",
        category=InvariantCategory.SCALE_AND_PERFORMANCE,
        enforcement_mechanism="Pagination parameters (limit/offset, cursor); limit bounds (max 100 items per page); generator-based queries.",
        test_suite="tests/test_phase56_persistence.py, tests/test_phase68_search_index.py",
        test_cases=[
            "test_paginated_checkpoint_history_retrieval",
            "test_search_results_page_bounded_memory",
        ],
    ),
    InvariantId.I_18: InvariantDefinition(
        id=InvariantId.I_18,
        title="Non-Breaking Backward Compatibility",
        description="Optional new fields, schemas, or extensions never break older valid records or legacy storage layouts.",
        category=InvariantCategory.DATA_INTEGRITY_AND_RECOVERY,
        enforcement_mechanism="Default values for new dataclass fields; fallback mappings; backward-compatible migration bridges.",
        test_suite="tests/test_phase54_checkpoint.py, tests/test_serialization.py",
        test_cases=[
            "test_checkpoint_minimal_creation_and_defaults",
            "test_legacy_handoff_checkpoint_migration_compatibility",
        ],
    ),
    InvariantId.I_19: InvariantDefinition(
        id=InvariantId.I_19,
        title="Empirical Evidence for System Claims",
        description="Do not claim encryption, atomicity, durability, or performance without verified implementation and tests.",
        category=InvariantCategory.ENGINEERING_VERIFICATION,
        enforcement_mechanism="Automated verification test suites; honest error recording; zero simulated claims without passing tests.",
        test_suite="tests/test_phase51_audit.py, tests/test_phase52_baseline.py",
        test_cases=[
            "test_atomic_file_persistence_and_snapshots",
            "test_baseline_test_suite_passes_100_percent",
        ],
    ),
    InvariantId.I_20: InvariantDefinition(
        id=InvariantId.I_20,
        title="Honest & Reproducible Verification Evidence",
        description="Every milestone, phase, and release includes honest, reproducible test execution reports with zero fabrication.",
        category=InvariantCategory.ENGINEERING_VERIFICATION,
        enforcement_mechanism="Structured phase completion reports saved in docs/reports/; exit code check; zero mocked passes.",
        test_suite="tests/test_phase50_discovery.py, tests/test_phase55_invariants_and_adr.py",
        test_cases=[
            "test_phase50_report_file_exists",
            "test_all_twenty_invariants_have_registered_test_coverage",
        ],
    ),
}


# ==============================================================================
# TRANSACTION & RECOVERY BOUNDARIES
# ==============================================================================

class TransactionOperation(str, Enum):
    COMMIT = "commit"
    BRANCH = "branch"
    RESTORE = "restore"
    IMPORT = "import"
    RETENTION = "retention"
    MIGRATION = "migration"


@dataclass(frozen=True)
class TransactionBoundary:
    """Formal definition of transaction and recovery semantics for storage operations."""
    operation: TransactionOperation
    atomicity_mechanism: str
    pre_condition: str
    failure_recovery: str
    audit_record_created: bool
    user_safe_error: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation": self.operation.value,
            "atomicity_mechanism": self.atomicity_mechanism,
            "pre_condition": self.pre_condition,
            "failure_recovery": self.failure_recovery,
            "audit_record_created": self.audit_record_created,
            "user_safe_error": self.user_safe_error,
        }


TRANSACTION_BOUNDARIES: Dict[TransactionOperation, TransactionBoundary] = {
    TransactionOperation.COMMIT: TransactionBoundary(
        operation=TransactionOperation.COMMIT,
        atomicity_mechanism="Write to .tmp file -> synchronous flush -> atomic file replace (replace()).",
        pre_condition="Valid Activity/Checkpoint domain entity passing validate() checks.",
        failure_recovery="Temporary file unlinked on error; original authoritative file intact; CommitFailedError raised.",
        audit_record_created=True,
        user_safe_error="CommitFailedError: The checkpoint could not be saved to disk. No state was modified.",
    ),
    TransactionOperation.BRANCH: TransactionBoundary(
        operation=TransactionOperation.BRANCH,
        atomicity_mechanism="Atomic creation of new Activity record linked to parent checkpoint without modifying source activity.",
        pre_condition="Target parent checkpoint exists and is valid.",
        failure_recovery="New branch directory/files discarded if initialization fails; original branch completely untouched.",
        audit_record_created=True,
        user_safe_error="BranchFailedError: Could not create branch from the specified checkpoint. Source timeline is unchanged.",
    ),
    TransactionOperation.RESTORE: TransactionBoundary(
        operation=TransactionOperation.RESTORE,
        atomicity_mechanism="Pre-restore safety snapshot taken; atomic workspace update; RESTORE audit checkpoint committed.",
        pre_condition="Target checkpoint exists, is compatible, and user has explicitly confirmed.",
        failure_recovery="Rollback to pre-restore safety snapshot if workspace hydration fails; no forward checkpoints deleted.",
        audit_record_created=True,
        user_safe_error="UnsafeRestoreError: Restore aborted due to validation failure. Workspace restored to pre-restore state.",
    ),
    TransactionOperation.IMPORT: TransactionBoundary(
        operation=TransactionOperation.IMPORT,
        atomicity_mechanism="Complete in-memory schema validation and relation graph verification prior to disk write.",
        pre_condition="Import payload satisfies Schema 1.0.0+ and passes secret/path traversal sanitization.",
        failure_recovery="Import aborted immediately upon first validation error; live storage is never touched.",
        audit_record_created=True,
        user_safe_error="ImportValidationError: The imported data is invalid or incompatible. No records were modified.",
    ),
    TransactionOperation.RETENTION: TransactionBoundary(
        operation=TransactionOperation.RETENTION,
        atomicity_mechanism="Ancestry tree graph walk marking reachable and protected checkpoints; batch atomic index update.",
        pre_condition="Protected milestones, branch heads, and required ancestors must not be in deletion set.",
        failure_recovery="Retention aborted if ancestry constraints cannot be satisfied; RetentionLimitError raised.",
        audit_record_created=True,
        user_safe_error="RetentionLimitError: Cannot prune history without compromising required checkpoint ancestry.",
    ),
    TransactionOperation.MIGRATION: TransactionBoundary(
        operation=TransactionOperation.MIGRATION,
        atomicity_mechanism="Versioned transformation to staging directory; full validation; atomic directory swap; safety backup.",
        pre_condition="Source schema version recognized; destination directory writable; free disk space verified.",
        failure_recovery="Rollback to pre-migration backup; migration marked FAILED with detailed diagnostic log.",
        audit_record_created=True,
        user_safe_error="MigrationError: Schema migration could not be completed safely. All existing data was preserved.",
    ),
}


# ==============================================================================
# USER-SAFE ERROR HIERARCHY
# ==============================================================================

def _sanitize_error_text(text: str) -> str:
    """Sanitizes user-facing error text to ensure zero secret leakage (Phase 82)."""
    if not text or not isinstance(text, str):
        return ""
    import re
    # GitHub PAT
    t = re.sub(r"\b(ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36}\b", "<REDACTED_GITHUB_TOKEN>", text)
    # AWS Access Key
    t = re.sub(r"\b(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b", "<REDACTED_AWS_KEY>", t)
    # Key-value secrets / passwords
    t = re.sub(r"(?i)(password|secret|token|api_key|passwd|access_key)\s*[:=]\s*['\"]?[^\s'\";,&]+['\"]?", r"\1=<REDACTED>", t)
    # Bearer tokens
    t = re.sub(r"\bBearer\s+[a-zA-Z0-9_\-\.]{15,}\b", "Bearer <REDACTED_TOKEN>", t)
    return t


class ContinuumUserError(Exception):
    """
    Base class for user-safe errors in Project Continuum (Phase 82).
    Guarantees:
    - Errors state what failed, whether data committed, and next steps.
    - User-facing message is clean, actionable, and strictly free of sensitive tokens or system secrets.
    - Diagnostic technical details are retained in 'internal_details' for logging.
    """
    def __init__(
        self,
        user_message: str,
        suggested_action: str = "",
        error_code: str = "ERR_CONTINUUM_GENERIC",
        internal_details: Optional[str] = None,
        remediable: bool = True,
        what_failed: Optional[str] = None,
        data_committed: bool = False,
        next_steps: Optional[str] = None,
    ):
        clean_msg = _sanitize_error_text(user_message)
        clean_action = _sanitize_error_text(suggested_action or next_steps or "")
        clean_failed = _sanitize_error_text(what_failed or user_message)

        super().__init__(clean_msg)
        self.user_message = clean_msg
        self.suggested_action = clean_action
        self.next_steps = clean_action
        self.what_failed = clean_failed
        self.data_committed = bool(data_committed)
        self.error_code = error_code
        self.internal_details = internal_details or ""
        self.remediable = remediable

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.user_message,
            "what_failed": self.what_failed,
            "data_committed": self.data_committed,
            "data_committed_statement": "YES (Data committed to disk)" if self.data_committed else "NO (Authoritative records remain unchanged)",
            "next_steps": self.next_steps,
            "suggested_action": self.suggested_action,
            "remediable": self.remediable,
        }


class InvariantViolationError(ContinuumUserError):
    """Raised when an architectural invariant constraint would be violated."""
    def __init__(self, invariant_id: InvariantId, message: str, suggested_action: str = ""):
        super().__init__(
            user_message=f"Invariant violation [{invariant_id.value}]: {message}",
            suggested_action=suggested_action or "Review operation constraints to ensure architectural invariants are respected.",
            error_code=f"ERR_INVARIANT_{invariant_id.name}",
            what_failed=f"Architectural invariant [{invariant_id.value}] would be violated: {message}",
            data_committed=False,
            next_steps=suggested_action or "Review operation constraints to ensure architectural invariants are respected.",
        )
        self.invariant_id = invariant_id


class CommitFailedError(ContinuumUserError):
    """Raised when an authoritative checkpoint commit fails disk persistence."""
    def __init__(self, message: str, internal_details: Optional[str] = None):
        super().__init__(
            user_message=f"Commit failed: {message}",
            suggested_action="Ensure the workspace directory is writable and disk space is available, then retry. No changes were committed.",
            error_code="ERR_STORAGE_COMMIT_FAILED",
            internal_details=internal_details,
            what_failed=f"Checkpoint commit failed to write to disk: {message}",
            data_committed=False,
            next_steps="Ensure the workspace directory is writable and disk space is available, then retry. No changes were committed.",
        )


class UnsafeRestoreError(ContinuumUserError):
    """Raised when a state restore cannot proceed safely."""
    def __init__(self, message: str, internal_details: Optional[str] = None):
        super().__init__(
            user_message=f"Restore aborted: {message}",
            suggested_action="Verify target checkpoint integrity or select an alternate historical checkpoint. Existing timeline was NOT altered.",
            error_code="ERR_RESTORE_UNSAFE",
            internal_details=internal_details,
            what_failed=f"State restore aborted: {message}",
            data_committed=False,
            next_steps="Verify target checkpoint integrity or select an alternate historical checkpoint. Existing timeline was NOT altered.",
        )


class ImportValidationError(ContinuumUserError):
    """Raised when an external import payload fails validation before write."""
    def __init__(self, message: str, validation_errors: Optional[List[str]] = None):
        action = f"Correct validation issues ({', '.join(validation_errors[:3])}) and retry." if validation_errors else "Verify the import file schema and integrity."
        super().__init__(
            user_message=f"Import validation failed: {message}",
            suggested_action=action,
            error_code="ERR_IMPORT_VALIDATION",
            internal_details="; ".join(validation_errors) if validation_errors else None,
            what_failed=f"Import archive pre-mutation validation failed: {message}",
            data_committed=False,
            next_steps=action,
        )
        self.validation_errors = validation_errors or []


class RetentionLimitError(ContinuumUserError):
    """Raised when history pruning cannot safely satisfy ancestry constraints."""
    def __init__(self, message: str):
        action = "Increase history retention quota or unmark non-essential protected checkpoints."
        super().__init__(
            user_message=f"Retention limit cannot be met: {message}",
            suggested_action=action,
            error_code="ERR_RETENTION_ANCESTRY_GUARD",
            what_failed=f"Retention pruning cannot safely satisfy ancestry constraints: {message}",
            data_committed=False,
            next_steps=action,
        )


class MigrationError(ContinuumUserError):
    """Raised when schema migration encounters an unrecoverable discrepancy."""
    def __init__(self, message: str, internal_details: Optional[str] = None):
        action = "Review migration diagnostics. Your existing data remains intact in .continuum/backup/."
        super().__init__(
            user_message=f"Migration error: {message}",
            suggested_action=action,
            error_code="ERR_MIGRATION_FAILED",
            internal_details=internal_details,
            what_failed=f"Schema migration error: {message}",
            data_committed=False,
            next_steps=action,
        )


# ==============================================================================
# ARCHITECTURE DECISION RECORD (ADR-001)
# ==============================================================================

@dataclass(frozen=True)
class ArchitectureDecisionRecord:
    """Formal Architecture Decision Record structure."""
    id: str
    title: str
    status: str
    date: str
    context: str
    decision: str
    persistence_boundary_choice: str
    rationale: str
    consequences_positive: List[str]
    consequences_tradeoffs: List[str]
    repository_evidence: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "date": self.date,
            "context": self.context,
            "decision": self.decision,
            "persistence_boundary_choice": self.persistence_boundary_choice,
            "rationale": self.rationale,
            "consequences_positive": list(self.consequences_positive),
            "consequences_tradeoffs": list(self.consequences_tradeoffs),
            "repository_evidence": list(self.repository_evidence),
        }


ADR_001 = ArchitectureDecisionRecord(
    id="ADR-001",
    title="Hybrid Partitioned JSON Authoritative Store + Embedded SQLite Derived Index",
    status="ACCEPTED",
    date="2026-10-16",
    context=(
        "Continuum v1.4.0 introduces the 'Universal Resume Anywhere' engine targeting thousands of "
        "activities and tens of thousands of checkpoints. The existing v1.0.0 storage persists a single "
        "monolithic `.continuum/state.json` file. Continuing to store all activities and checkpoints inside "
        "a single JSON file would require loading the entire history into memory on every access, violating "
        "I-17 (bounded memory retrieval), producing severe write latency, and risking Windows NTFS file-lock contention."
    ),
    decision=(
        "Adopt a hybrid architecture consisting of:\n"
        "1. Authoritative Store: Partitioned JSON files organized as:\n"
        "   - `.continuum/activities/<activity_id>/activity.json`\n"
        "   - `.continuum/activities/<activity_id>/checkpoints/<checkpoint_id>.json`\n"
        "   All writes use crash-safe atomic swaps (.tmp -> replace).\n"
        "2. Derived Index Store: Embedded SQLite database (`.continuum/index.db`) using Python's standard library `sqlite3`.\n"
        "   Indexes activities, checkpoint metadata, and full-text search (FTS5).\n"
        "   The SQLite index is strictly derived (I-06) and can be 100% deterministically rebuilt from the JSON files at any time."
    ),
    persistence_boundary_choice=(
        "Standard library Python `sqlite3` + atomic JSON file persistence. "
        "No third-party database, no separate server process, no external dependencies."
    ),
    rationale=(
        "1. Zero Production Dependencies: Python's built-in `sqlite3` is always available across Windows, macOS, and Linux.\n"
        "2. Strict Invariant Compliance: I-06 requires summaries and indexes to be derived; if `.continuum/index.db` is "
        "corrupted or deleted, it is completely rebuilt from authoritative JSON files.\n"
        "3. Scalability: Partitioning allows loading only the active activity and current checkpoint into memory, enabling "
        "sub-second operations even with 50,000+ checkpoints (I-17).\n"
        "4. Human Inspectability & Disaster Recovery: Authoritative JSON files remain plain text, version-controllable, "
        "and readable without specialized database tooling."
    ),
    consequences_positive=[
        "100% zero external dependencies preserved (strictly standard library).",
        "Sub-millisecond paginated history retrieval and search queries via SQLite B-tree & FTS5 indexes.",
        "Authoritative records are human-readable, crash-safe, and Git-friendly partitioned JSON files.",
        "Zero data loss if SQLite file is corrupted: 100% rebuildable from authoritative files.",
        "Eliminates monolithic file lock contention on Windows NTFS.",
    ],
    consequences_tradeoffs=[
        "Requires maintaining a dual-write sync layer where authoritative JSON writes trigger index updates.",
        "Requires automated index rebuild handler when discrepancy or SQLite corruption is detected.",
    ],
    repository_evidence=[
        "storage/manager.py: Demonstrates atomic .tmp file replacement pattern (MOVEFILE_REPLACE_EXISTING).",
        "storage/recovery.py: Demonstrates auto-recovery from corrupted files via snapshots.",
        "core/schema.py: Demonstrates strict schema validation boundaries.",
        "tests/test_phase51_audit.py: Certifies atomic durability and 0-dependency architecture.",
    ],
)


def get_invariant(inv_id: InvariantId) -> InvariantDefinition:
    """Retrieve the formal specification for an invariant."""
    if inv_id not in INVARIANT_REGISTRY:
        raise KeyError(f"Unknown invariant ID: {inv_id}")
    return INVARIANT_REGISTRY[inv_id]


def get_all_invariants() -> List[InvariantDefinition]:
    """Retrieve all 20 invariant definitions in order."""
    return [INVARIANT_REGISTRY[inv_id] for inv_id in InvariantId]
