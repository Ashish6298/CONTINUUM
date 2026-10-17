# Project Continuum v1.4.0 — Comprehensive Architecture & Reference Guide

> **Milestone 45**: Regression, Documentation and Release Readiness  
> **Phase 84**: Documentation and Compatibility  
> **Core Principle**: 100% Local-First, Zero External Dependencies, Offline-Guaranteed AI Work Continuity

---

## 1. Executive Summary & Core Philosophy

Project Continuum is an open-source engineering system designed to solve the **context loss and fragmentation problem** in AI-assisted software engineering. When developers switch between AI models (e.g., Claude, ChatGPT, Gemini, local LLMs) or between different development environments, critical context, verified reality, architectural decisions, and tactical next steps are routinely lost or distorted by conversational summaries.

Continuum provides:
- **Zero Cloud / Zero Telemetry**: 100% local processing; never transmits telemetry, code, or context to remote servers.
- **Authoritative JSON Ground Truth**: Human-readable, transparent JSON files stored directly within the workspace (`.continuum/activities/`).
- **Standard Library Only**: Written exclusively in standard Python 3.10+ with zero external package dependencies.
- **Fast Local Search & Indexing**: SQLite FTS5 derived index for sub-millisecond filtering and instant search, completely rebuildable from authoritative JSON at any time.

---

## 2. Mental Model & 3-State Separation Architecture

Continuum enforces strict isolation between three distinct layers of project truth:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                          3-STATE SEPARATION ENGINE                          │
├──────────────────────────┬──────────────────────────┬───────────────────────┤
│  1. PHYSICAL STATE       │  2. CONVERSATIONAL STATE │  3. AGENT EXECUTION   │
│     (Ground Truth)       │     (Assistant Claims)   │     (In-Flight Work)  │
├──────────────────────────┼──────────────────────────┼───────────────────────┤
│ • Git HEAD & status      │ • User requirements      │ • Current active task │
│ • AST Symbols (Py, JS/TS)│ • Stated decisions       │ • In-flight file edits│
│ • Test suite results     │ • Agent promises         │ • Last error raised   │
│ • Physical files on disk │ • Assumptions & blockers │ • Tactical next action│
└──────────────────────────┴──────────────────────────┴───────────────────────┘
```

1. **Physical Project State (`ProjectState`)**: Authoritative reality verified from disk, AST parsers, and test runners. Claims made in chat cannot mutate physical state without verified file modifications on disk.
2. **Conversational State (`ConversationalState`)**: Ingested dialogue, stated intentions, user requirements, and claims made by language models.
3. **Agent Execution State (`AgentExecutionState`)**: Tactical, in-flight work items, active tasks, uncommitted file modifications, and error conditions.

When conversational claims contradict physical disk reality, Continuum generates an explicit `ContradictionRecord` instead of overwriting verified ground truth.

---

## 3. Domain Model & Invariants

Continuum domain models are strongly typed, immutable-friendly dataclasses enforcing 25 core architectural invariants:

### 3.1 Primary Entities

#### `Activity`
Represents an ongoing stream of related work, feature development, bug fix, or research task:
- `id`: Stable local identifier (e.g. `act_abc123456789`).
- `title`: Human-readable summary.
- `description`: Detailed scope of the work stream.
- `activity_type`: `TASK`, `FEATURE`, `BUGFIX`, `REFACTOR`, `EXPLORATION`.
- `status`: Lifecycle state (`ACTIVE`, `PAUSED`, `COMPLETED`, `ARCHIVED`).
- `tags`: User or system classification tags.
- `collection`: Logical collection grouping (e.g. `frontend`, `billing`).
- `related_activity_ids`: Directed lineage and relationship references.
- `created_at` / `updated_at`: ISO 8601 UTC timestamps.
- `metadata`: Extensible dictionary for branch provenance and custom properties.

#### `UniversalCheckpoint`
Represents an authoritative, immutable state snapshot along an activity's timeline:
- `id`: Stable local identifier (e.g. `chk_1234567890ab`).
- `activity_id`: ID of parent activity.
- `parent_checkpoint_id`: Preceding checkpoint in lineage DAG (`None` for root).
- `branch_source_checkpoint_id`: Originating checkpoint if created via branching.
- `timestamp`: UTC ISO 8601 commit timestamp.
- `structured_state`: Key-value domain state payload.
- `progress`: Quantitative progress dictionary (percentage, milestone).
- `completed_work`: List of completed task strings.
- `pending_actions`: Ordered list of actionable next tasks.
- `decisions`: List of `DecisionRecord` objects.
- `context`: High-level prose narrative.
- `references`: URLs, tickets, documentation links.
- `blockers`: Active blockers and unresolved questions.
- `artifacts`: List of `ArtifactReference` objects.
- `provenance`: `ProvenanceRecord` detailing author, tool, and authority.
- `metadata`: System tags, retention protection flags, trigger provenance.
- `resume_brief`: Derived, deterministic resume briefing.

#### `DecisionRecord`
Authoritative record of architectural decisions:
- `id`: Decision identifier.
- `decision`: Succinct architectural choice made.
- `rationale`: Context and reason for the choice.
- `constraints`: List of enforced constraints.
- `recorded_at`: Timestamp of decision.

#### `ArtifactReference`
Link to relevant project artifacts without silent repository bloat:
- `name`: Display name.
- `path_or_uri`: Relative workspace path or URI.
- `mode`: `ArtifactMode.REFERENCE` (default: links to file) or `ArtifactMode.SNAPSHOT` (stores bounded copy up to 64KB).
- `captured_at`: Capture timestamp.
- `checksum_sha256`: SHA-256 integrity hash of content.
- `size_bytes`: Byte length of resource.
- `snapshot_content`: Bounded text payload (only if mode is `SNAPSHOT`).

---

## 4. Lifecycle & State Machine

Activities transition deterministically between defined lifecycle states:

```text
       ┌──────────────┐
       │   PENDING    │
       └──────┬───────┘
              │ (Start / Commit Checkpoint)
              ▼
       ┌──────────────┐   (Pause)   ┌──────────────┐
       │    ACTIVE    ├────────────►│    PAUSED    │
       └──────┬───────┘◄────────────┴──────────────┘
              │ (Complete) (Resume)
              ▼
       ┌──────────────┐
       │  COMPLETED   │
       └──────┬───────┘
              │ (Archive)
              ▼
       ┌──────────────┐
       │   ARCHIVED   │
       └──────────────┘
```

- **Reopening**: An activity in `COMPLETED` or `PAUSED` state can be reopened to `ACTIVE` with audit timestamps recorded in activity metadata.
- **Invariants**: Transitioning activity state preserves all historical checkpoints and never deletes timeline data (I-03).

---

## 5. Checkpoint Lineage DAG & Diff Engine

Continuum models checkpoint histories as a Directed Acyclic Graph (DAG) with explicit parent references (`parent_checkpoint_id`).

### Checkpoint Comparison (`CheckpointDiffEngine`)
The diff engine performs pure functional, read-only comparisons between any two checkpoints:
- **Progress Deltas**: Calculates percentage and milestone transitions.
- **List Diffs**: Categorizes `completed_work`, `pending_actions`, and `blockers` into `added`, `removed`, and `persisting` sets.
- **Decision Diffs**: Identifies new decisions, modified rationale/constraints, and removed decisions.
- **Notes & Context Diffs**: Unified text diff format for context changes.
- **Artifact Diffs**: Compares metadata, size changes, and checksums without loading large binary payloads into memory (I-17).

---

## 6. Branch vs. Restore: Semantic Matrix

Continuum strictly distinguishes between **Branching** and **Restoring**:

| Dimension | Branch Operation (`branch_from_checkpoint`) | Restore Operation (`confirm_restore`) |
| :--- | :--- | :--- |
| **Intent** | Explore alternative architectural paths or parallel experiments without altering original work. | Roll back to an earlier verified state while preserving all history for auditing. |
| **Activity Identity** | Creates a **new independent Activity** with unique `id` and title. | Reinstates state within the **same Activity**. |
| **History Impact** | Source activity and its checkpoints remain completely untouched (I-03). | **Never deletes newer checkpoints**. Appends a new checkpoint representing historical state. |
| **Parent Checkpoint** | `parent_checkpoint_id = None`; `branch_source_checkpoint_id = source_chk.id`. | `parent_checkpoint_id = current_head_chk.id`; `restored_from = target_chk.id`. |
| **Lineage DAG** | Spawns a new independent DAG root linked via ancestry metadata. | Continues existing linear or branching DAG forward. |

---

## 7. Local Search & SQLite FTS5 Indexing

Continuum features an instant, local full-text search engine:
- **Index Contents**: Indexed fields include activity title/description/tags, checkpoint context, completed work, pending actions, decisions, and blockers.
- **Speed**: Query execution under 60ms even with 50,000+ records.
- **Disaster Rebuild (I-06)**: The SQLite database (`.continuum/index.db`) contains zero authoritative data. If deleted or corrupted, calling `rebuild_index()` reconstructs 100% of the index from the authoritative `.continuum/activities/**/*.json` files.
- **Substring Fallback**: If full-text index is undergoing rebuild or encountering syntax errors, a robust fallback automatically scans local records.

---

## 8. Configurable Automatic Triggers

Continuum supports both manual and automated checkpointing:
- **Manual Primary**: Manual checkpoints (`continuum checkpoint`) always remain authoritative.
- **Trigger Types**:
  - `SCHEDULED`: Time-interval triggers (e.g., every 30 minutes of active editing).
  - `INTEGRATION_EVENT`: Git post-commit, build completion, test suite execution.
  - `MEANINGFUL_CHANGE`: Significant AST symbol changes or test state transitions.
- **Safety Safeguards**:
  - Strictly opt-in per trigger type.
  - Automatic deduplication prevents duplicate identical checkpoints.
  - Bounded exponential backoff retry.
  - Complete failure isolation: trigger crashes cannot corrupt core state.

---

## 9. Artifacts: References vs. Snapshots

To prevent repository bloat while preserving reproducible context:
- **Reference Mode (`ArtifactMode.REFERENCE`)**: Records file path, size, and SHA-256 checksum. Never copies raw contents into `.continuum`. Ideal for large files, binaries, and repo code.
- **Snapshot Mode (`ArtifactMode.SNAPSHOT`)**: Stores inline content for small configuration files, environment variables, or snippets (strictly bounded to <= 64KB).
- **Privacy Enforcement**: All snapshots are passed through the Continuum Secret Sanitizer to redact credentials, private keys, and custom denied terms.

---

## 10. Safe Retention Engine

Work continuity generates history over time. Continuum's retention engine ensures disk bounds without risk of data loss:
- **Protected Checkpoints**:
  - Head checkpoints are **always protected** from pruning.
  - Checkpoints explicitly pinned or flagged with `is_protected: true` are immune.
  - Checkpoints with unique architectural decisions are preserved.
- **Dry-Run Preview**: `preview_retention()` returns exact candidate counts and reclaimed bytes before mutation.
- **Undo Buffer**: Pruned checkpoints are moved to a local retention trash buffer (`.continuum/retention_backups/`) for safe recovery.
- **No Blind Deletion Loops**: If storage limits cannot be satisfied without deleting protected checkpoints, the engine stops and notifies the user rather than blindly deleting critical work.

---

## 11. Privacy, Zero Telemetry & AI Consent

- **Zero External Telemetry**: No network sockets opened to external hosts; no analytics or usage beacons.
- **Inline Secret Redaction**: Deterministic regex scrubber redacts GitHub PATs, AWS keys, OpenAI/Anthropic/Google API keys, Bearer tokens, private SSH keys, and passwords.
- **Deterministic Briefs**: Resume briefs are generated 100% offline using deterministic rule-based algorithms.
- **AI Enhancement Consent**: AI-enhanced briefing requires explicit user opt-in (`ai_consent.granted = True`), with transparent warnings of external payload dispatch.

---

## 12. Omni-Model Handoff Adapters

Continuum formats project state for optimal comprehension by specific LLMs:
- **`ClaudeAdapter`**: Semantic XML tags (`<project_metadata>`, `<verified_architecture>`, `<active_blockers>`) optimized for Claude prompt caching and deep reasoning.
- **`CodexGptAdapter`**: Concise Markdown bullet lists and fenced code blocks optimized for OpenAI models.
- **`GeminiAdapter`**: Structured sections and entity key-value dictionaries tailored for Google Gemini context windows.
- **`LocalModelAdapter`**: Minimal token-budget formatting tailored for quantized 7B/13B parameter local LLMs.

---

## 13. Export, Backup, Import & Disaster Recovery

Continuum provides two distinct export mechanisms:

### 13.1 Portable Versioned Export (`PortableExportEngine`)
- **Format**: `.continuum-export.tar.gz` (`continuum-export-v1.0`).
- **Scope**: User-selected activities and checkpoints for sharing with teammates or transferring specific tasks.
- **Integrity**: Lineage DAG preservation and checksum verification. Explicitly labeled as a selective export, not a complete disaster-recovery backup.

### 13.2 Complete Backup (`CompleteBackupEngine`)
- **Format**: `.continuum-backup.tar.gz` (`continuum-backup-v1.0`).
- **Scope**: Full workspace archive containing all activities, all checkpoints, configuration files, and SHA-256 integrity manifest.

### 13.3 Staged Import Engine (`CompleteImportEngine`)
- **Pre-Mutation Validation**: Validates archive version, manifest checksums, JSON schemas, and DAG integrity before touching live storage.
- **Staging Area**: Unpacks into an isolated temporary directory.
- **Conflict Strategies**:
  - `REJECT`: Fails safely if an entity ID already exists.
  - `RENAME_NEW`: Assigns fresh IDs to conflicting incoming records while preserving relationships.
  - `OVERWRITE`: Explicitly permitted overwrite with rollback backup.
  - `SKIP`: Preserves existing local records and imports non-conflicting entities.
  - `DEDUPLICATE`: Skips entities with identical content hashes.
- **Crash Resilience**: Atomic filesystem commit; interruptions roll back cleanly via journal. Rebuilds SQLite FTS5 index automatically upon import completion.

---

## 14. Performance Targets & Empirical Benchmarks

Verified empirical performance on standard hardware (Intel i7 / Apple M-series equivalent):
- Checkpoint commit + index latency: **< 15 ms**
- Full-text search and combined filtering: **< 60 ms** (typically 2–8 ms)
- Peak memory footprint: **< 50 MB** during large multi-checkpoint operations
- Archive creation & verification throughput: **> 1,000 checkpoints/second**
- Rebuild index from scratch: **< 500 ms** for 10,000 checkpoints

---

## 15. Accessibility & Web UI Standards

The embedded local Web Dashboard adheres to **WCAG 2.1 AA** standards:
- **Keyboard Navigation**: 100% accessible via Tab, Shift+Tab, Enter, Space, and Escape.
- **Focus Restoration**: Closing modals and dialogs restores keyboard focus to the triggering element.
- **High-Contrast Focus Indicators**: Visible `:focus-visible` outlines on all interactive elements.
- **Color-Independent Status**: State is communicated via clear text, distinct icons, and border styles, never color alone.
- **ARIA Live Regions**: Screen-reader announcements for dynamic updates (`role="status"`, `aria-live="polite"`).

---

## 16. Supported Platforms, Hardware Constraints & Deferred Features

### Supported Platforms
- **Operating Systems**: Windows 10/11, macOS 12+, Linux (Ubuntu, Debian, Fedora, Arch, Alpine).
- **Runtimes**: Python 3.10, 3.11, 3.12, 3.13+.
- **Hardware Footprint**: Bounded memory (<50MB RAM), minimal CPU overhead.

### Intentional Constraints & Non-Goals
- **Single-User Local-First**: Continuum is designed for single-developer local workspace usage. It does not provide real-time multi-user collaborative editing.
- **Zero Unsolicited Network Access**: No cloud sync daemons, external telemetry, or central database connections.
- **Explicit Capture Primacy**: Continuum never runs silent background screen scrapers or global keyloggers.

### Deferred Features (Future Roadmap)
- P2P encrypted LAN peer discovery.
- Native mobile companion application.
- Real-time multi-agent consensus engine.
