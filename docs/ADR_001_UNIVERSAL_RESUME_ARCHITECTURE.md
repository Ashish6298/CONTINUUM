# Architecture Decision Record (ADR-001) & Invariant Matrix

**Document:** ADR-001  
**Title:** Universal Resume Anywhere Architecture & Invariant Verification Matrix  
**Milestone:** 36 (Domain Model and Invariants) — Phase 55  
**Status:** **ACCEPTED**  
**Date:** 2026-10-16  
**Author:** Continuum Engineering  

---

## 1. Context & Problem Statement

Project Continuum v1.4.0 introduces the **Universal Resume Anywhere** engine, designed to support:
1. Seamless work continuity across any AI model, tool, or IDE without vendor lock-in.
2. Managing **thousands of activities** and **tens of thousands of checkpoints** (Target 27).
3. Sub-second paginated timeline retrieval and fast local search (Target 27, Invariant I-17).
4. Strictly **zero external network dependencies** or telemetry (Invariant I-09, Target 26).
5. 100% crash-safe local persistence with deterministic recovery (Invariants I-02, I-05, I-14).

### The Discovery Baseline
As audited in **Phase 50 (Inventory)** and **Phase 51 (Persistence Audit)**:
- Existing v1.0.0 persistence serializes a single monolithic JSON file at `.continuum/state.json` via atomic `.tmp -> replace` swaps.
- While atomic and safe for single-session snapshots, storing tens of thousands of checkpoints in a single file causes:
  * **O(N) Memory Exhaustion:** Loading the file requires parsing the entire multi-megabyte history into RAM on every read/write.
  * **Disk Write Amplification:** Every new checkpoint appends to a monolithic document, triggering full file rewrites.
  * **Concurrency & Lock Contention:** High frequency writes on Windows NTFS increase `PermissionError` file-locking risks.
  * **Violation of Invariant I-17:** Fails the bounded memory retrieval requirement.

---

## 2. Decision & Persistence Boundary Choice

Continuum adopts a **Hybrid Partitioned JSON Authoritative Store with an Embedded SQLite Derived Index**:

```text
 ┌────────────────────────────────────────────────────────────────────────┐
 │                      WORKSPACE LOCAL CONTINUITY                        │
 └────────────────────────────────────┬───────────────────────────────────┘
                                      │
              ┌───────────────────────┴───────────────────────┐
              ▼                                               ▼
┌───────────────────────────────┐           ┌───────────────────────────────────┐
│     AUTHORITATIVE STORE       │           │        DERIVED INDEX STORE        │
│    (Crash-Safe JSON Files)    │           │     (Embedded SQLite Database)    │
├───────────────────────────────┤           ├───────────────────────────────────┤
│ • .continuum/activities/      │           │ • .continuum/index.db             │
│   ├── act_01/activity.json    │           │ • Standard Library sqlite3 only   │
│   └── act_01/checkpoints/     │ ──Sync──► │ • B-Tree indexed queries          │
│       ├── chk_01.json         │           │ • FTS5 Full-Text Search index     │
│       └── chk_02.json         │           │ • Non-authoritative (I-06)        │
│ • Atomic swaps (.tmp -> move) │           │ • 100% Rebuildable on corruption  │
│ • Human-readable, Git-friendly│           │ • Sub-millisecond pagination      │
└───────────────────────────────┘           └───────────────────────────────────┘
```

### Persistence Boundary Specifications:
1. **Authoritative Ground Truth:**
   - Partitioned by Activity: `.continuum/activities/<activity_id>/activity.json`.
   - Partitioned by Checkpoint: `.continuum/activities/<activity_id>/checkpoints/<checkpoint_id>.json`.
   - Every write executes a two-phase atomic write (`.tmp` -> synchronous disk flush -> `os.replace`).
   - Plain JSON format guarantees that history is human-inspectable, recoverable with standard text editors, and zero-dependency.

2. **Derived Index Layer:**
   - Embedded SQLite database at `.continuum/index.db`.
   - Uses Python's built-in `sqlite3` module (zero external dependencies).
   - Indexed tables: `activities_idx`, `checkpoints_idx`, `fts_search_idx`.
   - **Crucial Invariant (I-06):** The SQLite database is strictly a derived index. If deleted or corrupted, it is completely rebuilt by scanning the authoritative JSON partitions.

---

## 3. Invariants Verification Matrix (I-01 through I-20)

| ID | Title | Category | Enforcement Mechanism | Test Suite & Verification |
|:---|:---|:---|:---|:---|
| **I-01** | Stable IDs | Identity & Lifecycle | `act_<hex>` / `chk_<hex>` UUIDv4 generation; immutable IDs across renames and edits. | `tests/test_phase53_activity.py`<br/>`tests/test_phase54_checkpoint.py` |
| **I-02** | Durable Commit Confirmation | Durability & Transaction | Two-phase atomic write (`.tmp -> replace`); synchronous disk flush before confirmation return. | `tests/test_phase51_audit.py`<br/>`tests/test_phase56_persistence.py` |
| **I-03** | Read-Only Historical Views | Data Integrity & Recovery | Defensive copy on retrieval; write prevention on historical records; explicit restore boundary. | `tests/test_phase54_checkpoint.py`<br/>`tests/test_phase62_history_view.py` |
| **I-04** | Non-Destructive Branching | Identity & Lifecycle | Creation of independent continuation activity linked to `parent_checkpoint_id`; source timeline untouched. | `tests/test_phase54_checkpoint.py`<br/>`tests/test_phase63_branching.py` |
| **I-05** | Explicit & Safe Restore | Data Integrity & Recovery | Pre-restore safety snapshot; `RESTORE` audit checkpoint committed; forward checkpoints preserved. | `tests/test_phase51_audit.py`<br/>`tests/test_phase64_restore.py` |
| **I-06** | Derived Briefs & Indexes | Data Integrity & Recovery | Checkpoint structured fields authoritative; `ResumeBrief.is_authoritative = False`; index rebuild engine. | `tests/test_phase54_checkpoint.py`<br/>`tests/test_phase60_briefs.py` |
| **I-07** | Privacy-Preserving Search | Security & Privacy | Credential sanitization & regex masking applied before indexing or snippet generation. | `tests/test_phase51_audit.py`<br/>`tests/test_phase65_search.py` |
| **I-08** | Bounded Automation | Scale & Performance | Opt-in `auto_capture` configuration; SHA-256 deduplication hashing; bounded event queues. | `tests/test_verification_extractor.py`<br/>`tests/test_phase61_automation.py` |
| **I-09** | External AI Consent | Security & Privacy | Zero outbound network calls by default; loopback-only binding; explicit user consent gate. | `tests/test_phase51_audit.py`<br/>`tests/test_state_isolation.py` |
| **I-10** | Comprehensive Secret Redaction | Security & Privacy | `SecretSanitizer` with 10+ entropy and regex matchers; exclusion of `.env`, `*.key`, `*.pem`. | `tests/test_phase51_audit.py`<br/>`tests/test_server_api.py` |
| **I-11** | Guarded Ancestry & Retention | Data Integrity & Recovery | Ancestry graph walk; protection markers on branch heads & milestones; `RetentionLimitError`. | `tests/test_phase58_recovery.py`<br/>`tests/test_phase64_retention.py` |
| **I-12** | Pre-Write Import Validation | Data Integrity & Recovery | In-memory schema and relational foreign-key validation prior to disk mutation. | `tests/test_phase51_audit.py`<br/>`tests/test_phase70_import.py` |
| **I-13** | Self-Contained Backup Scopes | Data Integrity & Recovery | Manifest-driven backup archiver validating completeness of referenced activities and checkpoints. | `tests/test_phase51_audit.py`<br/>`tests/test_phase71_backup.py` |
| **I-14** | Idempotent Migration | Data Integrity & Recovery | Staging area migration; pre-migration snapshot; idempotent re-runs; clear diagnostics. | `tests/test_phase54_checkpoint.py`<br/>`tests/test_phase57_migration.py` |
| **I-15** | Adapter Invariant Enforcement | Security & Privacy | External adapters consume domain entities; adapter outputs pass through serializer & sanitizer. | `tests/test_phase51_audit.py`<br/>`tests/test_phase54_checkpoint.py` |
| **I-16** | Lifecycle State Machine | Identity & Lifecycle | `VALID_STATUS_TRANSITIONS` table; `InvalidStatusTransitionError`; full history preservation. | `tests/test_phase53_activity.py` |
| **I-17** | Bounded Retrieval & Streaming | Scale & Performance | Pagination parameters (`limit`, `offset`, `cursor`); upper limit bound (max 100); generator streams. | `tests/test_phase56_persistence.py`<br/>`tests/test_phase65_search.py` |
| **I-18** | Backward Compatibility | Data Integrity & Recovery | Optional new dataclass fields with defaults; legacy `HandoffCheckpoint` migration bridge. | `tests/test_phase54_checkpoint.py`<br/>`tests/test_schema.py` |
| **I-19** | Empirical Claims Evidence | Engineering Verification | Automated verification test suites; zero simulated claims without passing unit and integration tests. | `tests/test_phase51_audit.py`<br/>`tests/test_phase52_baseline.py` |
| **I-20** | Honest Verification Reports | Engineering Verification | Structured phase completion reports saved in `docs/reports/`; exit code checks; zero mock passes. | `tests/test_phase50_discovery.py`<br/>`tests/test_phase55_invariants_and_adr.py` |

---

## 4. Transaction & Recovery Boundaries

```text
OPERATION    ATOMICITY MECHANISM           PRE-CONDITION                  FAILURE RECOVERY
──────────   ───────────────────────────   ────────────────────────────   ─────────────────────────────────────────────
COMMIT       .tmp write -> replace()       Valid domain entity            Unlink .tmp; raise CommitFailedError
BRANCH       New activity record created   Target parent checkpoint valid Discard branch init; source timeline untouched
RESTORE      Pre-restore snapshot taken    Target checkpoint valid & confirmed Rollback to snapshot; raise UnsafeRestoreError
IMPORT       In-memory validation first    Passes Schema 1.0.0+ checks    Abort import; live storage untouched
RETENTION    Ancestry graph walk           Protected items excluded       Abort pruning; raise RetentionLimitError
MIGRATION    Staging dir -> atomic swap    Schema version recognized      Rollback to .continuum/backup/; raise MigrationError
```

---

## 5. User-Safe Error Hierarchy

All user-facing exceptions inherit from [`ContinuumUserError`](file:///D:/CONTINUUM/core/invariants.py):
- **Safety Guarantee:** Clean, user-actionable explanations with zero leaked credentials, file paths, or private tokens.
- **Remediation:** Provides explicit `suggested_action` for the engineer.
- **Technical Diagnostics:** Internal stack traces and diagnostics are isolated in `internal_details`.

Hierarchy:
```text
Exception
  └── ContinuumUserError
        ├── InvariantViolationError
        ├── CommitFailedError
        ├── UnsafeRestoreError
        ├── ImportValidationError
        ├── RetentionLimitError
        └── MigrationError
```

---

## 6. Consequences & Repository Evidence

### Positive Consequences:
1. **Zero External Dependencies:** Built entirely with Python standard library (`sqlite3`, `pathlib`, `os`, `json`, `dataclasses`).
2. **Crash-Safe Durability:** Monolithic file corruption is eliminated; every checkpoint is isolated.
3. **High Performance at Scale:** Fast B-tree queries and FTS5 search indexing allow sub-second timeline operations even with 50,000+ checkpoints.
4. **Resilience:** If the SQLite index file is damaged, deleted, or missing, it can be regenerated at any time from authoritative JSON files.

### Repository Evidence:
- `storage/manager.py`: Validated atomic temporary file replacement (`replace()`).
- `storage/recovery.py`: Validated automated snapshot recovery.
- `core/schema.py`: Validated strict JSON Schema draft 2020-12 validation.
- `tests/test_phase51_audit.py`: Validated atomic writes and 0-dependency architecture.
- `tests/test_phase53_activity.py`: Validated activity lifecycle state machine.
- `tests/test_phase54_checkpoint.py`: Validated checkpoint provenance and legacy compatibility.
