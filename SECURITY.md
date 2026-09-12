# Security Policy

Project Continuum takes security and user privacy seriously. As a tool that inspects codebases, arbitrates state, and generates AI handoff bundles, Continuum is built around strict local isolation and data sanitization guarantees.

---

## 🛡️ Supported Versions

| Version | Supported |
| :--- | :---: |
| **1.0.x** | ✅ |
| **< 1.0.0** | ❌ |

---

## 🔒 Security & Privacy Guarantees

Continuum implements the following core security controls:

### 1. Zero External Telemetry
- Continuum operates **100% offline and locally**.
- It does not transmit telemetry, usage statistics, workspace contents, or handoff bundles to external servers or cloud services.

### 2. Secret & Credential Sanitization
- Secret-scanning extractors automatically scan for patterns matching API keys, tokens, private certificates, and environment secrets (`.env`, `id_rsa`, AWS tokens, OpenAI keys, etc.).
- Sensitive variables are scrubbed or masked before being written into state snapshots or handoff summaries.

### 3. Strict Workspace Boundary Enforcement
- All filesystem operations are strictly bound within the root workspace directory.
- Path traversal sequences (e.g. `../../etc/passwd` or symbolic links pointing outside the workspace) are rejected and ignored during AST and evidence extraction.

### 4. Atomic File Operations
- All state serialization writes (`project-state.json`, `.continuum/state.json`) use atomic file swap mechanisms (`.tmp` -> sync -> rename) to eliminate race conditions and prevent partial file corruption.

---

## 🚨 Reporting a Vulnerability

If you discover a security vulnerability or sensitive data leakage risk in Project Continuum, please do **NOT** open a public issue on GitHub.

Instead, report it responsibly to the project maintainers:

1. **Email**: [security@projectcontinuum.dev](mailto:security@projectcontinuum.dev) (or via GitHub Private Vulnerability Reporting on the repository).
2. **Include**:
   - A clear description of the vulnerability.
   - Steps to reproduce the issue (including a minimal workspace example).
   - Potential impact and any suggested remediations.

We will acknowledge receipt of your vulnerability report within 48 hours and work with you on a timeline for verification and release of a patch.
