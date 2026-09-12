<a id="top"></a>
<div align="center">

```text
  █▀▀ █▀█ █▄ █ ▀█▀ █ █▄ █ █ █ █ █ █▀▄▀█
  █▄▄ █▄█ █ ▀█  █  █ █ ▀█ █▄█ █▄█ █ ▀ █
```
### *AI Work Continuity & Cross-Model Agent Handoff System*

<p align="center">
  <b>An open-source engineering engine that captures, verifies, and packages your project state for seamless continuity across AI coding assistants and models such as Claude, GPT, Gemini, Cursor, Antigravity, Local LLMs, etc.</b>
</p>

```text
  [01] Extract Physical State  ──►  [02] Arbitrate Ground Truth  ──►  [03] Build State DAG  ──►  [04] Package Handoff
```

<br/>

<table>
  <tr>
    <td align="center"><a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=plastic&logo=python&logoColor=white" alt="Python 3.10+"/></a></td>
    <td align="center"><a href="https://pypi.org/project/continuum/"><img src="https://img.shields.io/badge/Downloads-PyPI-007EC6?style=plastic&logo=pypi&logoColor=white" alt="Downloads"/></a></td>
    <td align="center"><a href="tests/"><img src="https://img.shields.io/badge/Tests-126%2F126_Passed-00C853?style=plastic&logo=checkmarx&logoColor=white" alt="Tests Passed"/></a></td>
    <td align="center"><a href="docs/ARCHITECTURE.md"><img src="https://img.shields.io/badge/Architecture-3--State_Engine-7F77DD?style=plastic&logo=diagramsdotnet&logoColor=white" alt="3-State Architecture"/></a></td>
  </tr>
  <tr>
    <td align="center"><a href="https://json-schema.org/"><img src="https://img.shields.io/badge/Schema-Draft_7-2962FF?style=plastic&logo=json&logoColor=white" alt="JSON Schema"/></a></td>
    <td align="center"><a href="docs/CLI_REFERENCE.md"><img src="https://img.shields.io/badge/CLI-Smart_1--Command-FF6B6B?style=plastic&logo=gnometerminal&logoColor=white" alt="Smart 1-Command CLI"/></a></td>
    <td align="center"><a href="#testing--verification"><img src="https://img.shields.io/badge/Privacy-Zero_Telemetry-17A2B8?style=plastic&logo=openaccess&logoColor=white" alt="Zero Telemetry"/></a></td>
    <td align="center"><a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-F5A623?style=plastic&logo=open-source-initiative&logoColor=white" alt="MIT License"/></a></td>
  </tr>
</table>

<br>

</div>

## 🧭 Navigation

<pre>
# SYSTEM NAVIGATION MAP
 ├── <b>[01] FOUNDATION & BENCHMARK</b>
 │    ├── ❯ <a href="#what-is-continuum"><b>Overview & Core Problem</b></a>
 │    ├── ❯ <a href="#why-continuum-over-chat-summaries"><b>Benchmark: Continuum vs Chat Summaries</b></a>
 │    └── ❯ <a href="#quick-start-guide"><b>1-Command Quickstart Guide</b></a>
 │
 ├── <b>[02] ARCHITECTURE & GROUND TRUTH</b>
 │    ├── ❯ <a href="#three-state-separation-architecture"><b>3-State Separation Engine</b></a>
 │    ├── ❯ <a href="#5-tier-evidence-hierarchy-matrix"><b>5-Tier Evidence Arbitration Matrix</b></a>
 │    └── ❯ <a href="#canonical-state-graph-dag"><b>Canonical Dependency Graph (DAG)</b></a>
 │
 └── <b>[03] TOOLING & GOVERNANCE</b>
      ├── ❯ <a href="#smart-omni-model-handoff-adapters"><b>Omni-Model Handoff Adapters</b></a>
      ├── ❯ <a href="#complete-cli-reference"><b>Complete CLI Command Reference</b></a>
      ├── ❯ <a href="#verified-roadmap-all-24-phases"><b>Roadmap to v1.0.0 (All 24 Phases)</b></a>
      ├── ❯ <a href="#testing--verification"><b>Testing & Verification</b></a>
      ├── ❯ <a href="#contributing"><b>Contributing Guide</b></a>
      ├── ❯ <a href="#code-of-conduct"><b>Code of Conduct</b></a>
      ├── ❯ <a href="#security"><b>Security & Privacy</b></a>
      └── ❯ <a href="#license"><b>License</b></a>
</pre>

<br>

<a id="what-is-continuum"></a>
## 💡 What is Continuum?

> **Continuum** is an open-source work continuity platform for multi-agent software engineering. It automatically extracts, arbitrates, and packages verified workspace state — enabling seamless, zero-drift handoffs across Claude, GPT-4o, Gemini, Cursor, and local LLMs.

<br/>

<table>
  <tr>
    <th width="28%" align="left"><b>Feature Pillar</b></th>
    <th width="72%" align="left"><b>Architecture & Capabilities</b></th>
  </tr>
  <tr>
    <td><b>🏛️ 3-State Engine</b></td>
    <td>Strict ontological separation between <b>Project State</b> (AST symbols, files, tests), <b>Conversational State</b> (requirements, chat claims), and <b>Agent Execution State</b> (in-flight edits).</td>
  </tr>
  <tr>
    <td><b>⚖️ 5-Tier Truth Matrix</b></td>
    <td>Proof-grounded arbitration engine. When conversational claims conflict with codebase reality, physical evidence strictly takes precedence with automated contradiction logging.</td>
  </tr>
  <tr>
    <td><b>🕸️ State Graph (DAG)</b></td>
    <td>Topological Directed Acyclic Graph connecting milestones to code symbols. Automatically propagates <code>STALE</code> invalidations downstream when files change.</td>
  </tr>
  <tr>
    <td><b>🤖 Omni-Model Handoff</b></td>
    <td>Single-command generation of model-native context packages tailored for <b>Claude</b> (XML tagged), <b>GPT/Codex</b>, <b>Gemini</b>, and <b>Local LLMs</b>.</td>
  </tr>
  <tr>
    <td><b>🛡️ Autonomous Governance</b></td>
    <td>Background observer daemon paired with non-blocking Git commit hooks, SHA-256 state provenance, corruption self-healing, and 100% local zero telemetry.</td>
  </tr>
</table>

<br>

<a id="why-continuum-over-chat-summaries"></a>
## ⚔️ Why Continuum over Chat Summaries?

> Conversational summaries degrade across sessions because they record what agents *say*, not what exists on disk. Continuum replaces subjective chat memory with verified codebase state.

```text
[WITHOUT CONTINUUM]
  Chat Logs ──► LLM Compression ──► Context Drift ──► Broken Agent Handoff ❌

[WITH CONTINUUM]
  Workspace ──► AST & Test Proof ──► 5-Tier Truth ──► Seamless Omni-Handoff ✅
```

### 📊 Capability Benchmark Matrix

```text
🔬 AST & Symbol Grounding
   • Chat Summaries    ░░░░░░░░░░  [0/10]  (Zero Code Awareness)
   • Custom Scripts    ████░░░░░░  [4/10]  (Regex / Naive Parsing)
   • ⬢ CONTINUUM       ██████████  [10/10] (Polyglot AST & Full Symbol Resolution)

⚖️ Contradiction Detection
   • Chat Summaries    ░░░░░░░░░░  [0/10]  (Propagates Hallucinations)
   • Custom Scripts    ░░░░░░░░░░  [0/10]  (No Conflict Ledger)
   • ⬢ CONTINUUM       ██████████  [10/10] (5-Tier Proof Arbitration)

🕸️ Dependency Graph (DAG)
   • Chat Summaries    ░░░░░░░░░░  [0/10]  (Flat Text Memory)
   • Custom Scripts    █░░░░░░░░░  [1/10]  (Ad-hoc File Lists)
   • ⬢ CONTINUUM       ██████████  [10/10] (Topological DAG & Stale Propagation)

📦 Omni-Model Handoffs
   • Chat Summaries    ██░░░░░░░░  [2/10]  (Copy-Paste Prompts)
   • Custom Scripts    ████░░░░░░  [4/10]  (Single-Model Output)
   • ⬢ CONTINUUM       ██████████  [10/10] (Claude, GPT-4o, Gemini, Local LLMs)

🛡️ State Self-Healing
   • Chat Summaries    ░░░░░░░░░░  [0/10]  (Zero Recovery)
   • Custom Scripts    ░░░░░░░░░░  [0/10]  (No Snapshots)
   • ⬢ CONTINUUM       ██████████  [10/10] (Snapshot History & Auto-Recovery)

⚡ 1-Command Workflow
   • Chat Summaries    █░░░░░░░░░  [1/10]  (Manual Copy-Paste)
   • Custom Scripts    █████░░░░░  [5/10]  (Custom Flags Required)
   • ⬢ CONTINUUM       ██████████  [10/10] (Smart Auto-Init & Auto-Scan)
```

<br>

<a id="quick-start-guide"></a>
## ⚡ Quick Start Guide (1-Command)

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/Ashish6298/CONTINUUM.git
cd CONTINUUM

# Install globally in editable mode
pip install -e .
```

### 2. Generate an Instant AI Handoff (The 1-Command Workflow)

Run inside any project directory — Continuum automatically scans your codebase, extracts AST symbols, builds the dependency graph, and creates your ready-to-resume AI handoff package:

```bash
continuum handoff
```

### 3. Terminal Output

```text
                 █▀▀ █▀█ █▄ █ ▀█▀ █ █▄ █ █ █ █ █ █▀▄▀█
                 █▄▄ █▄█ █ ▀█  █  █ █ ▀█ █▄█ █▄█ █ ▀ █

             AI Work Continuity & Cross-Model Agent Handoff System
  ─────────────────────────────────────────────────────────────────────────────

    The one-Command Workflow: $ continuum handoff

    Automatically captures your project state, extracts AST symbols,
    and generates a ready-to-use 'ai_handoff/' package for your next
    AI Agent (Claude, GPT, Gemini, Cursor, Antigravity, etc.)

  ─────────────────────────────────────────────────────────────────────────────
  v1.0.0   python 3.11.4   mit license   

◈ [HANDOFF READY] Generated Omni-Model Continuity Package:

  Location: D:\myproject\ai_handoff

   ✦ Universal Handoff  →  D:\myproject\ai_handoff\handoff.md (Works for ANY model)

   ✦ Claude Optimized   →  D:\myproject\ai_handoff\claude_handoff.md

   ✦ GPT / Codex Plan   →  D:\myproject\ai_handoff\gpt_handoff.md

   ✦ Gemini Hierarchy   →  D:\myproject\ai_handoff\gemini_handoff.md

   ✦ Machine State      →  D:\myproject\ai_handoff\project-state.json

➤ [NEXT ACTION] Paste this prompt into your next AI Agent chat:

   "Read ai_handoff/handoff.md and continue the project."
```

<br>

<a id="three-state-separation-architecture"></a>
## 🏛️ Three-State Separation Architecture

Continuum enforces strict separation between physical code truth and conversational assertions:

```text
  ┌──────────────────────────────┐  ┌──────────────────────────────┐  ┌──────────────────────────────┐
  │  01. PHYSICAL PROJECT STATE  │  │  02. CONVERSATIONAL STATE    │  │  03. AGENT EXECUTION STATE   │
  ├──────────────────────────────┤  ├──────────────────────────────┤  ├──────────────────────────────┤
  │  • Physical Source Code      │  │  • User Intent & Goals       │  │  • Active Tactical Task      │
  │  • Polyglot AST Symbol Tree  │  │  • Architectural Decisions   │  │  • In-Flight File Changes    │
  │  • Git Working Tree & Diffs  │  │  • Agent Assertions & Claims │  │  • Transient Subprocess Logs │
  │  • Test Suite Pass/Fail Logs │  │  • Unresolved Open Questions │  │  • Deterministic Next Action │
  └──────────────┬───────────────┘  └──────────────┬───────────────┘  └──────────────┬───────────────┘
                 │                                 │                                 │
                 ▼                                 ▼                                 ▼
  ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
  │              ⬢ CANONICAL STATE ENGINE (Topological DAG Graph)                    │
  └──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

<br>

<a id="5-tier-evidence-hierarchy-matrix"></a>
## ⚖️ 5-Tier Evidence Hierarchy Matrix

When evidence sources conflict, Continuum arbitrates ground truth according to strict mathematical seniority:

```text
┌─ [L1] RUNTIME EXECUTION ────────────────────────────────────────────────────────┐
│  Artifacts: TEST_RUN, BUILD_LOG, RUNTIME_LOG                     Weight: 100%   │
│  Rule     : Absolute ground truth. Real execution exit codes govern status.     │
└─────────────────────────────────────────────────────────────────────────────────┘
┌─ [L2] AST SYNTAX & FILES ───────────────────────────────────────────────────────┐
│  Artifacts: SOURCE_CODE, AST_SYMBOL, MANIFEST                    Weight:  90%   │
│  Rule     : Physical code exports override git commit messages and chat claims. │
└─────────────────────────────────────────────────────────────────────────────────┘
┌─ [L3] VERSION CONTROL DELTAS ───────────────────────────────────────────────────┐
│  Artifacts: GIT_COMMIT, GIT_DIFF, GIT_STATUS                     Weight:  75%   │
│  Rule     : Historical changes override unverified comments and documentation.  │
└─────────────────────────────────────────────────────────────────────────────────┘
┌─ [L4] ARCHITECTURE DOCUMENTATION ───────────────────────────────────────────────┐
│  Artifacts: DOCUMENTATION, CODE_COMMENT                          Weight:  50%   │
│  Rule     : Informational context. Marked STALE when AST symbols change.        │
└─────────────────────────────────────────────────────────────────────────────────┘
┌─ [L5] CONVERSATIONAL AGENT CLAIMS ──────────────────────────────────────────────┐
│  Artifacts: CONVERSATION_ASSERTION, USER_REQUIREMENT             Weight:  25%   │
│  Rule     : Unverified hypothesis until proven on disk by Levels 1-3.           │
└─────────────────────────────────────────────────────────────────────────────────┘
```

<br>

<a id="canonical-state-graph-dag"></a>
## 🕸️ Canonical State Graph (DAG)

Continuum models all milestones, phases, AST symbols, requirements, and test suites as a topologically ordered Directed Acyclic Graph:

```text
  [MILESTONE] Core Architecture ──► [PHASE 0] Canonical Schema
                                           │
                    ┌──────────────────────┴──────────────────────┐
                    ▼                                             ▼
       [SERVICE] StorageManager                      [SERVICE] AstExtractor
                    │                                             │
                    ▼                                             ▼
       [TEST] test_serialization.py                 [TEST] test_workspace_extractor.py
       (Status: ✅ PASS)                            (Status: ✅ PASS)
```

```text
┌─ GRAPH ENGINE CAPABILITIES ─────────────────────────────────────────────────────────────┐
│  • Topological Invalidation : Modifying a service automatically marks downstream tests  │
│                               and modules as STALE.                                     │
│  • Cycle Detection & Guard  : Circular dependency insertions (A -> B -> A) are blocked │
│                               at graph construction time.                               │
│  • Subgraph Extraction      : AI context selectors extract minimal task-relevant slices │
│                               to stay within LLM token budgets.                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

<br>

<a id="smart-omni-model-handoff-adapters"></a>
## 🤖 Smart Omni-Model Handoff Adapters

Running `continuum handoff` compiles verified project state into 5 specialized model formats:

```text
  $ continuum handoff
           │
           ├── 🌐 [UNIVERSAL]   ──►  handoff.md          (Works for ANY model out of the box)
           ├── 🟣 [CLAUDE]      ──►  claude_handoff.md   (Strict Anthropic XML tag hierarchy)
           ├── 🟢 [GPT/CODEX]   ──►  gpt_handoff.md      (OpenAI plan-first step checklists)
           ├── 🔵 [GEMINI]      ──►  gemini_handoff.md   (DeepMind hierarchical ontology)
           └── ⚙️  [MACHINE]     ──►  project-state.json  (Machine-parseable Schema 1.0.0 AST)
```

<br>

<a id="complete-cli-reference"></a>
## 💻 Complete CLI Command Reference

```bash
# ── 1. INITIALIZATION & WORKSPACE ───────────────────────────────────────────
$ continuum init [--path .]                # Initialize .continuum storage & Git hooks
$ continuum scan [--path .]                # Full workspace AST extraction & DAG rebuild

# ── 2. STATE INSPECTION & GRAPH ─────────────────────────────────────────────
$ continuum status [--path .] [--json]     # Print verified project state & next action
$ continuum graph [--mermaid] [--stats]    # Inspect DAG structure or export Mermaid

# ── 3. AI HANDOFF GENERATION ────────────────────────────────────────────────
$ continuum handoff                        # Auto-scan & generate Omni-Model handoffs
$ continuum handoff --model claude         # Tailor specifically for Anthropic Claude
$ continuum handoff --model gpt            # Tailor for OpenAI GPT-4o / Codex
$ continuum handoff --model gemini         # Tailor for Google Gemini Pro

# ── 4. BACKGROUND OBSERVER DAEMON ───────────────────────────────────────────
$ continuum daemon start                   # Start background filesystem observer
$ continuum daemon status                  # Check background daemon health & cycles
$ continuum daemon run-once                # Trigger a single incremental scan pass
$ continuum daemon stop                    # Gracefully stop the background daemon
```

<br>

<a id="verified-roadmap-all-24-phases"></a>
## 🗺️ Architecture Milestones & Verification

Project Continuum v1.0.0 is fully certified with **126 / 126 automated tests passing (100%)** across all 24 roadmap phases (Milestones 1 through 8). Detailed engineering reports and verification logs are available in [docs/reports/](docs/reports/).

<br>

<a id="testing--verification"></a>
## 🧪 Testing & Enterprise Security

```bash
$ py tests/run_all_tests.py    # 126/126 Passed (100% Test Coverage across 24 Phases)
```

```text
┌─ SECURITY & PRIVACY CONTROLS ────────────────────────────────────────────────────────────┐
│  • Zero Telemetry      : 100% offline local processing with no external telemetry.       │
│  • Secret Sanitization : Automatically detects and strips API keys and credentials.      │
│  • Workspace Boundary  : Strict path-traversal prevention locking access to workspace.   │
│  • Atomic Swaps        : Crash-safe state serialization preventing corrupted files.      │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

<br>

<a id="contributing"></a>
## 🤝 Contributing

We welcome contributions from developers and researchers building the future of cross-model AI work continuity and agent handoffs.

**1. Clone Repository**
```bash
git clone https://github.com/Ashish6298/CONTINUUM.git
```

```bash
cd CONTINUUM
```

**2. Create a Feature Branch**
```bash
git checkout -b feature/ast-symbol-extractor
```

**3. Setup Virtual Environment**
```bash
python -m venv .venv
```

```bash
# On Windows:
.venv\Scripts\activate

# On macOS / Linux:
source .venv/bin/activate
```

**4. Install Development Dependencies**
```bash
pip install -e ".[dev]"
```

**5. Run Automated 24-Phase Test Suite**
```bash
py tests/run_all_tests.py
```

**6. Verify Architectural Invariants**
```text
┌─ ARCHITECTURAL INVARIANTS ───────────────────────────────────────────────────────────────┐
│  • 3-State Separation : Physical workspace state is never mutated by chat claims.         │
│  • Zero Telemetry     : 100% offline local processing with no external network calls.     │
│  • Atomic Persistence : All state writes use crash-safe atomic swaps (.tmp -> replace).   │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

**7. Commit & Open a Pull Request**
```bash
git commit -m "feat(extractors): add support for rust AST parser"
```

For complete architectural specifications, commit rules, and PR checklists, read **[CONTRIBUTING.md](CONTRIBUTING.md)**.

<br>

<a id="code-of-conduct"></a>
## 📜 Code of Conduct

Project Continuum strictly enforces the **Contributor Covenant v2.1** across all issues, pull requests, and community discussions.

```text
COMMUNITY GOVERNANCE STANDARDS
 ├── 🌟 CORE PLEDGE       ──►  Harassment-free experience regardless of background
 ├── 🤝 COLLABORATION     ──►  Constructive feedback & focus on what is best for the project
 └── ⚖️ ENFORCEMENT LADDER ──►  Correction ──► Warning ──► Temporary Ban ──► Permanent Ban
```

Detailed enforcement guidelines and reporting steps are available in **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)**.

<br>

<a id="security"></a>
## 🛡️ Security & Privacy

Continuum is built around verifiable, non-negotiable security invariants:

```text
STATUS       INVARIANT                 ENFORCEMENT GUARANTEE
──────────   ───────────────────────   ─────────────────────────────────────────────────────
[ENFORCED]   Zero External Telemetry   100% offline execution; no network calls or telemetry
[ENFORCED]   Secret Sanitization       Automatic regex & entropy masking for sensitive keys
[ENFORCED]   Workspace Containment     Rejection of symlinks and paths escaping root
[ENFORCED]   Atomic State Swaps        Zero partial writes; crash-safe file serialization
```

Read our complete policy and disclosure process in **[SECURITY.md](SECURITY.md)**.

<br>

<a id="license"></a>
## ⚖️ License

Project Continuum is open-source software licensed under the **[MIT License](LICENSE)**.

---

<div align="center">

```text
┌─ SUPPORT & COMMUNITY ────────────────────────────────────────────────────────────────────┐
│  ⭐ Star the Repo : Support open-source AI continuity on GitHub                          │
│  🐛 File an Issue : Report bugs, feature requests, or AST extractor ideas                │
│  💬 Discussions   : Share your multi-agent handoff setups & workflows                    │
│  ▲ Return to Top  : Jump back to system navigation & command reference                   │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

<p align="center">
  <a href="#top"><b>[ ▲ BACK TO TOP ]</b></a> &nbsp;&nbsp;&nbsp;
  <a href="https://github.com/Ashish6298/CONTINUUM"><b>[ ⭐ STAR REPOSITORY ]</b></a> &nbsp;&nbsp;&nbsp;
  <a href="https://github.com/Ashish6298/CONTINUUM/issues"><b>[ 🐛 REPORT ISSUE ]</b></a>
</p>

<sub>Project Continuum • Open-Source AI Work Continuity & Cross-Model Agent Handoff System</sub>

</div>

