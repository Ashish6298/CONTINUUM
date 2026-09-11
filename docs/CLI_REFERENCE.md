# Continuum CLI Reference & Usage Manual

The `continuum` command-line tool provides full control over project scanning, graph querying, handoff package generation, and continuous background observation.

---

## 💻 Commands Overview

```bash
# Initialize Continuum storage and hooks
continuum init [DIRECTORY] [--no-hooks]

# Scan workspace and generate verified canonical state
continuum scan [DIRECTORY] [--output-dir DIR]

# Check verification status, active contradictions, and next actions
continuum status [DIRECTORY]

# Query and inspect the Canonical State Graph (DAG)
continuum graph [DIRECTORY] [--mermaid] [--dot]

# Generate model-optimized AI Handoff Packages
continuum handoff [DIRECTORY] [--model claude|codex|gemini|local_llm|universal] [--task TASK] [--budget TOKENS] [--output-dir DIR]

# Manage background filesystem watcher daemon
continuum daemon start [DIRECTORY] [--interval SECONDS]
continuum daemon status [DIRECTORY]
continuum daemon stop [DIRECTORY]
```

---

## 1. `continuum init`
Initializes `.continuum/` directory storage (`state.json`, `history/`, `backup/`) and installs non-blocking Git hooks (`pre-commit`, `post-merge`) to track changes automatically.

```bash
continuum init .
```

---

## 2. `continuum scan`
Executes full multi-source evidence extraction (AST, manifests, Git tree, test discovery) and constructs the verified Canonical State.

```bash
continuum scan .
```

---

## 3. `continuum status`
Prints a high-level summary of verified components, identified contradictions, detected programming languages, and recommended next actions.

```bash
continuum status .
```

---

## 4. `continuum graph`
Inspects the Canonical State Graph DAG. Supports generating Mermaid diagrams for immediate visual inspection in Markdown renderers.

```bash
continuum graph . --mermaid
```

---

## 5. `continuum handoff`
Generates a structured, self-contained AI work handoff package tailored to specific model prompt structures:

- `--model claude`: Uses `<system_directives>`, `<project_state>`, `<architectural_context>`, `<task_assignment>` XML tags.
- `--model codex`: Uses markdown checklists and code fences optimized for OpenAI GPT-4 / Codex.
- `--model gemini`: Generates multi-tier hierarchical ontology sections with explicit dependency trees.
- `--model local_llm`: Produces ultra-compact, token-frugal context for local 7B–14B models.
- `--model universal`: Generates vendor-neutral `project-state.json` and Markdown handoff files.

```bash
continuum handoff . --model claude --task "Implement OAuth2 token revocation" --budget 3000 --output-dir ./handoff_claude
```

---

## 6. `continuum daemon`
Runs the continuous work memory observer in the background, updating state incrementally as source files are edited.

```bash
continuum daemon start .
continuum daemon status .
continuum daemon stop .
```
