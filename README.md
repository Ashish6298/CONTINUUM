# Project Continuum (AI Work Continuity & Agent Handoff System)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests: 100% Passed](https://img.shields.io/badge/tests-105%2F105%20passed-brightgreen.svg)](tests/)

Continuum is a portable, mathematically verifiable, and model-independent AI work continuity engine designed to preserve the physical truth of an ongoing software engineering project across different AI models, sessions, and platforms.

---

## 🚀 The Core Problem & Solution

Current AI coding workflows suffer from **context entrapment** and **hallucination propagation**. When a developer switches models (e.g. Claude to GPT-4o to Gemini to Local Llama) or context windows reset, conversational summaries distort reality by turning unverified chat claims into false progress.

**Project Continuum solves this fundamentally:**
> **"Physical project reality must always be kept separate from conversational claims."**

Continuum does not recreate old conversations; it reconstructs the verifiable physical reality resulting from ongoing work.

---

## 🏛️ The Three-State Separation Architecture

Continuum maintains strict ontological separation between three distinct realities:

```mermaid
graph TD
    subgraph "Project State (Physical Reality)"
        A1[Source Code & Files]
        A2[AST Symbols & Types]
        A3[Manifests & Dependencies]
        A4[Git Tree & Churn]
        A5[Test & Build Results]
    end

    subgraph "Conversational State (Intent & Reasoning)"
        B1[User Requirements]
        B2[Architectural Decisions]
        B3[Agent Claims / Assertions]
        B4[Assumptions & Unresolved Qs]
    end

    subgraph "Agent Execution State (Tactical In-Flight)"
        C1[Active Tactical Tasks]
        C2[In-Flight File Edits]
        C3[Transient Errors]
        C4[Next Action Recommendation]
    end

    A1 & A2 & A3 & A4 & A5 --> D[Canonical Project State Root]
    B1 & B2 & B3 & B4 --> D
    C1 & C2 & C3 & C4 --> D
```

---

## ⚖️ The Evidence Hierarchy Matrix

When evidence conflicts, Continuum arbitrates truth according to strict seniority:

1. **Level 1 (Highest)**: Runtime status & automated test execution exit codes (`TEST_RUN`, `BUILD_LOG`, `RUNTIME_LOG`).
2. **Level 2**: AST syntax trees, symbol exports, physical manifests (`SOURCE_CODE`, `AST_SYMBOL`, `CONFIG_FILE`).
3. **Level 3**: Git working tree diffs, staged index, commit history (`GIT_COMMIT`, `GIT_DIFF`, `GIT_STATUS`).
4. **Level 4**: Architecture documentation, comments, READMEs (`DOCUMENTATION`).
5. **Level 5 (Lowest)**: Conversational statements and AI agent claims (`CONVERSATION_ASSERTION`, `USER_REQUIREMENT`, `AGENT_CLAIM`).

---

## 🗺️ Roadmap & Phase Progress to v1.0.0

| Milestone | Phase | Title | Status |
| :--- | :---: | :--- | :---: |
| **Milestone 1** | **Phase 0** | Architecture, Canonical Ontology & Schema Foundation | ✅ **VERIFIED** |
| **Milestone 2** | **Phase 1** | Workspace & Source Code Evidence Extraction | ✅ **VERIFIED** |
| | **Phase 2** | Configuration, Environment & Metadata Extraction | ✅ **VERIFIED** |
| | **Phase 3** | Git History & Workspace Delta Analysis | ✅ **VERIFIED** |
| | **Phase 4** | Test, Build & Verification Evidence Collection | ✅ **VERIFIED** |
| | **Phase 5** | Conversation & Agent State Ingestion | ✅ **VERIFIED** |
| **Milestone 3** | **Phase 6** | Evidence Resolution Engine | ✅ **VERIFIED** |
| | **Phase 7** | Contradiction Detection Engine | ✅ **VERIFIED** |
| | **Phase 8** | Confidence Calculation & Verified Status Evaluation | ✅ **VERIFIED** |
| **Milestone 4** | **Phase 9** | State Graph (DAG) Construction | ✅ **VERIFIED** |
| | **Phase 10** | Dependency Invalidation & Status Propagation | ✅ **VERIFIED** |
| | **Phase 11** | Graph Persistence, Querying & Visualization | ✅ **VERIFIED** |
| **Milestone 5** | **Phase 12** | Task-Driven Context Selection | ✅ **VERIFIED** |
| | **Phase 13** | Context Pruning & Token Budget Optimization | ✅ **VERIFIED** |
| **Milestone 6** | **Phase 14** | Universal Handoff Package Generation | ✅ **VERIFIED** |
| | **Phase 15** | Model-Specific Handoff Adapters (Claude, Codex, Gemini, Local) | ✅ **VERIFIED** |
| **Milestone 7** | **Phase 16** | Filesystem Observation & Incremental State Updates | ✅ **VERIFIED** |
| | **Phase 17** | Git Hooks & Persistent State Management | ✅ **VERIFIED** |
| | **Phase 18** | Continuum Daemon & CLI | ✅ **VERIFIED** |
| **Milestone 8** | **Phase 19** | End-to-End Integration & Polyglot Validation | ⏳ *Next Phase* |
| | **Phase 20** | Adversarial Testing & Hallucination Resistance | ⏳ *Pending* |
| | **Phase 21** | Performance, Reliability & Data Integrity | ⏳ *Pending* |
| | **Phase 22** | Security, Privacy & Production Hardening | ⏳ *Pending* |
| | **Phase 23** | Documentation, Packaging & v1.0.0 Release | ⏳ *Pending* |

---

## 📂 Repository Structure

```text
CONTINUUM/
├── core/                        # Foundation & Canonical State (Phase 0)
│   ├── enums.py                 # Statuses, EvidenceTypes, EvidenceLevels, NodeTypes
│   ├── evidence.py              # Canonical Evidence & SHA-256 Provenance tracking
│   ├── state_models.py          # ProjectState, ConversationalState, AgentExecutionState
│   ├── interfaces.py            # Contracts for Extractors, Resolvers, Graph & Adapters
│   ├── schema.py                # JSON Schema generator & validation
│   └── serializer.py            # Deterministic, atomic JSON persistence
├── extractors/                  # Multi-Source Evidence Harvesters (Milestone 2)
│   ├── base.py                  # Base extractor & standard ignore filters
│   ├── workspace_extractor.py   # Phase 1: Workspace & language analysis
│   ├── config_extractor.py      # Phase 2: Manifests, lockfiles & container configs
│   ├── git_extractor.py         # Phase 3: Git status, branch, HEAD, churn & commit logs
│   ├── verification_extractor.py # Phase 4: Safe test & build execution (Level 1)
│   ├── conversation_extractor.py # Phase 5: Transcripts & claims ingestion (Level 5)
│   ├── config/
│   │   ├── parsers.py           # Multi-ecosystem manifest parsers
│   │   └── secret_sanitizer.py  # Zero-credential-leakage redaction engine
│   ├── parsers/
│   │   ├── base.py              # Parser protocol & result types
│   │   ├── python_parser.py     # Python AST class, method, function & export parser
│   │   ├── js_ts_parser.py      # JavaScript/TypeScript class, interface & type parser
│   │   └── comment_parser.py    # Universal TODO/FIXME/BUG marker extractor
│   └── verification/
│       └── runners.py           # Test runners & structured output parsers
├── resolution/                  # Truth Resolution & State Synthesis (Milestone 3 - Phase 6)
│   └── resolver.py              # Phase 6: Seniority arbitration & conflict preservation
├── contradictions/              # Discrepancy & Hallucination Defense (Milestone 3 - Phase 7)
│   ├── models.py                # ContradictionType, severity, and DiscrepancyLedger
│   └── detector.py              # Phase 7: Cross-boundary contradiction detector
├── confidence/                  # Confidence & Status Evaluation (Milestone 3 - Phase 8)
│   ├── models.py                # ConfidenceBreakdown & scoring schema
│   └── calculator.py            # Phase 8: Multi-dimensional confidence engine
├── graph/                       # Canonical Project State Graph (Milestone 4 - Phases 9, 10 & 11)
│   ├── models.py                # GraphValidationResult, GraphStats, PropagationResult
│   ├── manager.py               # Phase 9: State Graph (DAG) manager & visualizer
│   ├── propagator.py            # Phase 10: Invalidation propagation & actionable work engine
│   ├── snapshot.py              # Phase 11: Atomic versioned graph persistence & load
│   ├── diff.py                  # Phase 11: Semantic graph comparison & delta engine
│   └── query.py                 # Phase 11: Topologically indexed graph query engine
├── context/                     # Intelligent Context Selection (Milestone 5 - Phases 12 & 13)
│   ├── models.py                # TaskContext payload & Markdown briefing generator
│   ├── selector.py              # Phase 12: Task-driven context selector engine
│   └── pruner.py                # Phase 13: Priority-tiered context pruner & budget optimizer
├── handoff/                     # AI Model Handoff System (Milestone 6 - Phases 14 & 15)
│   ├── models.py                # HandoffPackage & atomic filesystem persistence
│   ├── packager.py              # Phase 14: Universal Handoff Package generator
│   └── adapters/                # Phase 15: Model-Specific Handoff Adapters
│       ├── base.py              # Base adapter protocol implementation
│       ├── claude_adapter.py    # Anthropic Claude XML-tagged adapter
│       ├── codex_gpt_adapter.py # OpenAI Codex / GPT-4 markdown adapter
│       ├── gemini_adapter.py    # Google Gemini hierarchical ontology adapter
│       └── local_model_adapter.py # Compact token-frugal adapter for local models
├── watcher/                     # Continuous Work Memory (Milestone 7 - Phase 16)
│   ├── models.py                # ChangeType, FileChangeEvent, IncrementalUpdateResult
│   ├── detector.py              # Phase 16: Filesystem change & delta detector
│   └── updater.py               # Phase 16: Incremental state updater & invalidator
├── storage/                     # Persistent State & Git Hooks (Milestone 7 - Phase 17)
│   ├── models.py                # StorageMetadata, RecoveryResult
│   ├── manager.py               # Phase 17: .continuum directory & snapshot storage
│   ├── recovery.py              # Phase 17: Corruption detection & auto-recovery
│   └── hooks.py                 # Phase 17: Non-blocking Git hook management
├── daemon/                      # Background Observer Service (Milestone 7 - Phase 18)
│   └── service.py               # Phase 18: Threaded daemon with run_once & background lifecycle
├── cli/                         # Developer & Agent Command Line (Milestone 7 - Phase 18)
│   └── main.py                  # Phase 18: init, status, scan, graph, handoff, daemon
├── tests/                       # Complete Test Suite (105 unit & integration tests)
│   ├── run_all_tests.py         # Test runner
│   ├── test_enums_and_evidence.py
│   ├── test_state_isolation.py
│   ├── test_serialization.py
│   ├── test_interfaces.py
│   ├── test_workspace_extractor.py
│   ├── test_config_extractor.py
│   ├── test_git_extractor.py
│   ├── test_verification_extractor.py
│   ├── test_conversation_extractor.py
│   ├── test_evidence_resolver.py
│   ├── test_contradiction_detector.py
│   ├── test_confidence_calculator.py
│   ├── test_state_graph.py
│   ├── test_dependency_propagation.py
│   ├── test_graph_persistence_and_querying.py
│   ├── test_context_selector.py
│   ├── test_context_pruning.py
│   ├── test_handoff_packager.py
│   ├── test_model_adapters.py
│   ├── test_incremental_updater.py
│   ├── test_persistent_storage_and_hooks.py
│   └── test_cli_and_daemon.py
├── docs/reports/                # Phase Verification & Completion Reports
└── pyproject.toml
```

---

## 💻 Developer CLI (`continuum`)

Initialize and manage verified state directly from the terminal:

```bash
# Initialize Continuum storage (.continuum/) and Git hooks
continuum init

# Scan workspace and build Canonical State Graph
continuum scan

# View verified status and next actions
continuum status

# Inspect Canonical State DAG and export Mermaid diagram
continuum graph --mermaid

# Generate an AI Handoff package for Claude, GPT, Gemini, or Local LLMs
continuum handoff --model claude --output-dir ./claude_handoff

# Manage background filesystem observer daemon
continuum daemon start
continuum daemon status
continuum daemon stop
```

---

## 🧪 Running Tests

To run the complete Continuum test suite:

```bash
python tests/run_all_tests.py
# Or using the Windows Python launcher:
py tests/run_all_tests.py
```
