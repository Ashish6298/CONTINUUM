# Continuum Quickstart & Installation Guide

---

## 📦 Installation

### From Source (Local Development)
```bash
# Clone the repository
git clone https://github.com/Ashish6298/CONTINUUM.git
cd CONTINUUM

# Install in editable mode
pip install -e .
```

### Requirements
- Python 3.10, 3.11, or 3.12
- Git (optional, for Git history & hook features)

---

## 🚀 5-Minute Quickstart

### Step 1: Initialize Continuum in your Project
Navigate to your project repository and initialize Continuum:
```bash
cd /path/to/my-project
continuum init
```
This creates `.continuum/` with automatic snapshot history and non-blocking Git hooks.

### Step 2: Run a Full Project Verification Scan
Scan files, parse AST symbols, identify dependencies, and detect contradictions:
```bash
continuum scan
```

### Step 3: View Verified Project Truth
Check project confidence, verified components, and detected discrepancies:
```bash
continuum status
```

### Step 4: Export Visual DAG Architecture
Generate an architecture graph in Mermaid format:
```bash
continuum graph --mermaid
```

### Step 5: Switch AI Models Seamlessly (Handoff Generation)
Prepare a context-optimized handoff package when switching from Claude to GPT or Gemini:
```bash
continuum handoff --model claude --task "Implement refresh token rotation" --output-dir ./claude_context
```

### Step 6: Enable Continuous Work Memory (Daemon)
Run the observer daemon so every file change is incrementally captured without manual scans:
```bash
continuum daemon start
```
