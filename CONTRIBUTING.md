# Contributing to Project Continuum

Thank you for your interest in contributing to **Project Continuum**! We welcome contributions from developers and researchers building the future of cross-model AI work continuity and agent handoffs.

---

## 🧭 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Architecture & Design Principles](#architecture--design-principles)
- [Development Setup](#development-setup)
- [Running Tests](#running-tests)
- [Contribution Workflow](#contribution-workflow)
- [Coding Guidelines](#coding-guidelines)
- [Security & Sensitive Data](#security--sensitive-data)

---

## 📜 Code of Conduct

All contributors are expected to adhere to our [Code of Conduct](CODE_OF_CONDUCT.md). Please treat others with respect, empathy, and professional courtesy.

---

## 🏗️ Architecture & Design Principles

Continuum is built around strict, deterministic engineering principles:

1. **Zero External Telemetry**: Continuum runs 100% locally and offline. No telemetry, tracking, or outbound network calls are allowed in core extractors or handoff generators.
2. **3-State Separation**: Never conflate Physical Workspace State, Conversational State, and Agent Execution State.
3. **5-Tier Evidence Hierarchy**: AST facts and physical file artifacts always outrank conversational statements or LLM self-assertions.
4. **Deterministic Schema**: All serialized state adheres to JSON Schema Draft 7 with atomic swap file writes (`.tmp` -> replace).

---

## 💻 Development Setup

### Prerequisites
- **Python 3.10+** (Python 3.10, 3.11, or 3.12 supported)
- **Git 2.20+**

### Local Setup Steps

```bash
# 1. Clone your fork
git clone https://github.com/<your-username>/CONTINUUM.git
cd CONTINUUM

# 2. Create a virtual environment (optional but recommended)
python -m venv .venv

# On Windows:
.venv\Scripts\activate
# On macOS / Linux:
source .venv/bin/activate

# 3. Install dependencies in editable mode
pip install -e ".[dev]"
```

---

## 🧪 Running Tests

Continuum maintains a 100% pass rate across all 24 architectural phases. Before submitting any changes, all tests must pass:

```bash
# Run the complete test suite across all 24 phases
python tests/run_all_tests.py

# Or use pytest directly
pytest tests/ -v
```

Expected output:
```text
================================================================================
CONTINUUM TEST EXECUTION SUMMARY
================================================================================
Total Tests Run: 126
Passed:         126
Failures:       0
Errors:         0
Overall Status: SUCCESS (100% Passed)
================================================================================
```

---

## 🔄 Contribution Workflow

1. **Fork & Branch**: Create a feature branch off `main` (or active development branch):
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. **Make Changes**: Keep changes modular, focused, and covered by automated tests.
3. **Test Thoroughly**: Ensure `python tests/run_all_tests.py` passes completely.
4. **Commit Conventions**: Use structured, clear commit messages:
   - `feat(extractors): add support for rust AST parsing`
   - `fix(daemon): handle lock contention during rapid file writes`
   - `docs(readme): clarify omni-model handoff adapters`
5. **Open a Pull Request**: Provide a clear description of the problem solved, changes made, and test validation evidence.

---

## 📐 Coding Guidelines

- **Python Standard Library**: Prefer standard library modules where feasible to minimize runtime dependencies.
- **Type Annotations**: Use Python type hints (`typing` / `dataclasses`) for public interfaces.
- **Path Sanitization**: Always use `os.path.normpath` or `pathlib.Path` to prevent path-traversal vulnerabilities.
- **Atomic I/O**: Use safe write patterns (write to `.tmp`, flush, atomic rename) for state persistence.

---

## 🛡️ Security & Sensitive Data

Never commit API keys, tokens, or environment credentials. If you find a security vulnerability, please follow our [Security Policy](SECURITY.md) rather than opening a public issue.
