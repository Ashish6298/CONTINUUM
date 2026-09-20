# Continuum Browser Companion & Cross-Model Handoff Guide

---

## 🧭 Overview

The **Continuum Browser Companion** is an ultra-portable, zero-token-waste context continuity layer for web-based AI coding assistants. It runs directly inside your browser across:
- **ChatGPT** (`https://chatgpt.com/`)
- **Claude.ai** (`https://claude.ai/`)
- **Google AI Studio** (`https://aistudio.google.com/`)
- **Google Gemini** (`https://gemini.google.com/`)
- **DeepSeek Chat** (`https://chat.deepseek.com/`)

With the Companion, developers can effortlessly migrate entire multi-turn coding sessions and verified code blocks from one AI model to another with a single click, eliminating tedious manual copy-pasting, prompt degradation, and hallucinations.

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                           CROSS-MODEL CONTINUITY WORKFLOW                                   │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
  [ChatGPT Session] ──► [DOM Extractor] ──► [ContextCompressor] ──► [CrossTab Relay / LocalStorage]
                                                                              │
                                                                              ▼
  [Local Workspace Files] ◄── [Workspace Sync] ◄── [Claude / Gemini] ◄── [DOM Synthetic Injector]
```

---

## 📦 Installation & Distribution Modes

Continuum provides three zero-friction distribution channels:

### 1. Standalone Native Manifest V3 WebExtension (Recommended)
Zero external dependencies, 100% free, and runs natively in any Chromium-based browser (Chrome, Edge, Brave, Chromium).

**1-Command Auto-Launch:**
```bash
continuum launch
```
Continuum automatically discovers your installed Chromium browser and launches a new window with the extension pre-loaded.

**Manual Installation:**
1. Navigate to `chrome://extensions` or `edge://extensions`.
2. Enable **Developer mode** in the top right.
3. Click **Load unpacked** and select the `<continuum_root>/browser/extension` directory.

---

### 2. Tampermonkey / Violentmonkey Userscript
For developers using userscript managers:
1. Start the Continuum daemon: `continuum serve`.
2. Open `http://127.0.0.1:8765` and click **🧩 Install Companion** (or navigate to `http://127.0.0.1:8765/continuum.user.js`).
3. Click **Install** in Tampermonkey.

---

### 3. Zero-Install 1-Click Bookmarklet
For restricted corporate machines or mobile browsers where extensions cannot be installed:
1. Generate the bookmarklet installer:
   ```bash
   continuum bookmarklet --html ./installer.html
   ```
2. Open `installer.html` in your browser and drag the **Continuum Handoff** button to your Bookmarks Bar.
3. Click the bookmarklet on any ChatGPT or Claude conversation to trigger instant handoff extraction.

---

## ⚙️ Core Architecture & Engines

### 1. Multi-Platform Chat DOM Conversation & Code Extractor (`ChatConversationExtractor`)
- Extracts full conversation histories, isolating `user` prompts and `assistant` responses.
- Uses platform-specific DOM selectors (`data-message-author-role`, `.human-turn`, `user-query`, `.chat-message`).
- Identifies and isolates generated code blocks (`pre code`, prose containers), tagging language, file headers, and AST boundaries.

### 2. Context Compressor & Ground-Truth Prompt Synthesizer (`ContextCompressor`)
- **100% Code Preservation**: Verified code blocks are preserved verbatim as ground-truth artifacts.
- **Smart Token Budgeting**: Summarizes early conversational filler and chit-chat while retaining the last 2–3 turns verbatim for immediate conversational context.
- **Model-Tailored Synthesis**:
  - **Claude**: Anthropic-native XML tagging (`<project_continuation_context>`, `<verified_code_artifacts>`, `<immediate_task>`).
  - **Gemini**: DeepMind multi-tier hierarchical knowledge topology (`[1.0] PROJECT INTENT`, `[2.0] CODE REPOSITORY`).
  - **DeepSeek**: High-density markdown structure optimized for open-weight instruction tunings.
  - **ChatGPT**: OpenAI plan-first step checklists and fenced markdown blocks.

### 3. Cross-Tab Relay & Ephemeral Channel (`CrossTabHandoff`)
- Coordinates handoffs across browser tabs using an ephemeral `localStorage` relay channel (`continuum_handoff_relay`).
- Enforces strict **90-second TTL expiration** and single-consumption guarantees to prevent stale replay.
- Automatically routes and opens target model tabs (`https://claude.ai/new`, `https://gemini.google.com/app`, etc.).

### 4. Synthetic DOM Input Injector (`ContinuumDOMInjector`)
- Overcomes React controlled component state and ProseMirror rich-text editors.
- Dispatches a synthetic event pipeline: `beforeinput` &rarr; `InputEvent` &rarr; `Event('input')` &rarr; `Event('change')` &rarr; `KeyboardEvent('keyup')`.
- Includes automated clipboard fallbacks using `GM_setClipboard`, `navigator.clipboard`, and legacy `document.execCommand('copy')`.

### 5. Bi-Directional Browser-to-Workspace Code Sync (`POST /api/workspace/sync`)
- When running `continuum serve`, the companion allows developers to sync AI-generated code snippets directly into physical workspace files.
- Generates automatic timestamped backups in `.continuum/backup/` before overwriting existing files.
- Enforces workspace containment and rejects path-traversal attacks (`../`).

### 6. Multi-Turn Handoff History & Checkpointing (`HandoffCheckpointManager`)
- Maintains an immutable chain-of-custody across multi-model relays (e.g. `ChatGPT` &rarr; `Claude` &rarr; `Gemini`).
- Visualizes previous handoff snapshots in the companion modal timeline.
- Allows developers to re-branch conversations from any earlier snapshot with 1 click.

---

## ⌨️ Keyboard Shortcuts & Controls

| Shortcut / Element | Action |
| :--- | :--- |
| **`Alt + C`** | Open / Close Continuum Companion Modal |
| **`⬢ Continuum Badge`** | Click floating bottom-right badge to open modal |
| **Model Buttons (`Claude`, `Gemini`, `DeepSeek`)** | Trigger instant 1-click cross-tab relay to target model |
| **`Copy Handoff Prompt`** | Copy synthesized prompt to system clipboard |
| **`Sync to Workspace`** | Sync extracted code blocks directly to local files |
