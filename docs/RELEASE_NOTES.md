# Continuum Release Notes — v1.0.0

**Release Date:** September 11, 2026  
**Status:** General Availability (GA) — Production Ready  

---

## 🌟 Highlights of v1.0.0

Project Continuum v1.0.0 is the first complete, mathematically grounded AI work continuity and cross-model handoff engine for software engineering.

### 1. Three-State Segregation
- Strict separation between **Physical Project Reality** (files, AST symbols, test exit codes), **Conversational Intent** (requirements, agent claims), and **Tactical Execution State** (in-flight tasks, next actions).
- Conversational claims can never falsely become verified ground truth.

### 2. Multi-Source Evidence Harvesting
- Language-aware AST extractors for Python (classes, async/sync methods, docstrings) and JavaScript/TypeScript (interfaces, types, React components).
- Manifest and configuration extraction (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, Dockerfiles).
- Git tree extraction (commits, churn, branch status, dirty working trees).
- Safe build & test execution harvesting with process timeouts.

### 3. Truth Resolution & Contradiction Detection
- Seniority arbitration via the 5-tier Evidence Hierarchy Matrix.
- Real-time detection of false completion claims, test pass falsehoods, phantom documentation, and misleading Git commit messages.
- Grounded, explainable confidence calculation.

### 4. Canonical State Graph (DAG) & Dependency Invalidation
- High-performance DAG representing modules, classes, tests, requirements, and milestones.
- Cycle detection & prevention.
- Automated status invalidation (`STALE` / `BLOCKED` propagation) upon upstream file changes.

### 5. Task-Driven Context Selection & Token Budget Pruning
- Subgraph relevance filtering targeting specific task objectives.
- Greedy priority-based token budget pruning preserving critical architectural constraints.

### 6. Universal Handoff & Vendor-Specific Adapters
- **Universal Handoff Package**: `project-state.json`, `project-context.md`, `handoff.md`, evidence manifests.
- **Model Adapters**: Native XML for Anthropic Claude, markdown checklists for OpenAI Codex/GPT, hierarchical ontology for Google Gemini, and compact token-frugal formatting for local LLMs.

### 7. Continuous Work Memory
- Incremental state updater (~12–45 ms latency).
- Versioned snapshot persistence in `.continuum/history/`.
- Automatic crash recovery and corruption self-healing.
- Non-blocking Git hooks and background filesystem observer daemon.

---

## 🧪 Quality & Verification Metrics
- **126 Total Unit, Integration, Adversarial & Benchmark Tests (100% Passed)**
- **Polyglot validation** across Python, TypeScript, Full-stack repositories.
- **Zero credential leakage** with automated secret sanitization.
