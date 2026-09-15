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

# Launch Web Control Dashboard & REST API Daemon (v1.2.0)
continuum serve [DIRECTORY] [--port PORT] [--host HOST] [--no-browser] [--watch] [--status] [--stop]

# 1-Command Browser Launcher with Continuum Extension Pre-loaded (v1.2.0)
continuum launch [--target chatgpt|claude|gemini|aistudio|deepseek] [--dry-run]

# Generate Zero-Install Browser Handoff Bookmarklet (v1.2.0)
continuum bookmarklet [--raw] [--html PATH]
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

---

## 7. `continuum serve` (v1.2.0)
Launches the embedded Web Control Dashboard and REST API daemon on `http://127.0.0.1:8765`. Provides real-time context token budgeting, interactive prompt tailoring, bi-directional code sync, and companion userscript delivery.

```bash
# Launch dashboard and open in default browser
continuum serve

# Run headless daemon with background filesystem observation
continuum serve --no-browser --watch

# Check daemon health and retrieve session token
continuum serve --status

# Gracefully terminate daemon
continuum serve --stop
```

---

## 8. `continuum launch` (v1.2.0)
Auto-discovers your installed Chromium-based browser (Google Chrome, Microsoft Edge, Brave, Chromium) across Windows, macOS, and Linux, and opens a new window with the Continuum extension pre-loaded.

```bash
# Launch directly into ChatGPT
continuum launch

# Launch directly into Claude
continuum launch --target claude

# Launch directly into Google Gemini
continuum launch --target gemini

# Inspect launch arguments without starting process
continuum launch --target deepseek --dry-run
```

---

## 9. `continuum bookmarklet` (v1.2.0)
Generates an ultra-portable, zero-install JavaScript bookmarklet URI or interactive HTML installer for browsers where extension installations are restricted.

```bash
# Output executable javascript: URI to console
continuum bookmarklet --raw

# Generate interactive drag-and-drop installer HTML page
continuum bookmarklet --html ./install_bookmarklet.html
```
