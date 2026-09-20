# Continuum Web & Browser Integration Guide (v1.2.0)

This guide documents the architecture, setup instructions, security model, and troubleshooting steps for the **Continuum Local Web Control Dashboard** and **Browser Companion Userscript**.

---

## 1. Overview & Architecture

Continuum v1.2.0 introduces a zero-store-fee, local-first bridge between your physical workstation and in-browser AI chat interfaces (ChatGPT, Claude, Google AI Studio, Gemini, and DeepSeek).

```
┌────────────────────────────────────────────────────────┐
│                   YOUR WORKSTATION                     │
│                                                        │
│  [Physical Project Files] ──► [Continuum AST Scanners] │
│                                      │                 │
│                                      ▼                 │
│                         [HTTP Server Daemon (:8765)]   │
│                          (Token Auth + Sanitization)   │
└──────────────────────────────────────┬─────────────────┘
                                       │ Loopback HTTP (:8765)
                                       ▼
┌────────────────────────────────────────────────────────┐
│                   WEB BROWSER (ANY)                    │
│                                                        │
│  ┌───────────────────────┐   ┌───────────────────────┐ │
│  │ Web Control Dashboard │   │ In-Chat AI Companion  │ │
│  │  http://127.0.0.1:8765│   │   (Shadow DOM Badge)  │ │
│  │ • Live State Observer │   │ • ChatGPT / Claude    │ │
│  │ • Prompt Composer     │   │ • Gemini / DeepSeek   │ │
│  │ • 1-Click Clipboard   │   │ • Alt+C Quick-Menu    │ │
│  └───────────────────────┘   └───────────────────────┘ │
└────────────────────────────────────────────────────────┘
```

---

## 2. Quickstart: Starting the Local Daemon

To start the local background daemon on your active project directory:

```bash
# Start on current workspace
continuum serve

# Or explicitly designate a path and port
continuum serve --path /path/to/project --port 8765

# Open the Web Control Dashboard directly in your browser
continuum serve --open
```

Once started, the daemon provides:
- **Local Dashboard:** Accessible at `http://127.0.0.1:8765`
- **Dynamic Session Token:** Automatically created and written to `.continuum/daemon.token`
- **Zero Configuration Script:** Served at `http://127.0.0.1:8765/continuum.user.js`

---

## 3. Web AI Platform Compatibility Matrix

| AI Chat Platform | URL Match | DOM Input Type | Synthetic Framework Sync | Injection Modes |
| :--- | :--- | :--- | :---: | :---: |
| **ChatGPT** | `https://chatgpt.com/*` | ProseMirror ContentEditable / `#prompt-textarea` | ✅ Supported (React) | Replace, Prepend, Append |
| **Claude** | `https://claude.ai/*` | ProseMirror `.ProseMirror` ContentEditable | ✅ Supported (React) | Replace, Prepend, Append |
| **Google AI Studio** | `https://aistudio.google.com/*` | `textarea` / `div[role="textbox"]` | ✅ Supported (Angular) | Replace, Prepend, Append |
| **Gemini** | `https://gemini.google.com/*` | `div.textarea` / `div[role="textbox"]` | ✅ Supported (Lit/Angular) | Replace, Prepend, Append |
| **DeepSeek** | `https://chat.deepseek.com/*` | `textarea[placeholder*="Ask"]` | ✅ Supported (Vue/React) | Replace, Prepend, Append |

---

## 4. 1-Click Browser Companion Setup

1. **Install a Userscript Extension:**
   - [Tampermonkey](https://www.tampermonkey.net/) (Chrome, Firefox, Edge, Safari, Brave)
   - [Violentmonkey](https://violentmonkey.github.io/) (Open-source alternative)
2. **Install the Companion Script:**
   - With `continuum serve` running, open `http://127.0.0.1:8765/continuum.user.js` in your browser.
   - Your userscript extension will prompt you to install it with 1 click.
   - The script comes pre-configured with your active session authentication token.
3. **Open Your AI Chat:**
   - Navigate to ChatGPT, Claude, Gemini, or DeepSeek.
   - You will see the floating `[∞ Continuum]` badge at the bottom-right corner.
   - Press **`Alt + C`** (or click the badge) to open the Quick-Action menu and inject physical workspace context directly into the chat prompt.

---

## 5. Security & Isolation Model

- **Strict Loopback Binding:** The daemon strictly listens on `127.0.0.1` and automatically refuses external network interfaces (`0.0.0.0` is blocked).
- **Origin Validation & CORS:** Cross-Origin Resource Sharing (CORS) only permits whitelisted AI hosts (`chatgpt.com`, `claude.ai`, `aistudio.google.com`, `gemini.google.com`, `chat.deepseek.com`).
- **Cryptographic Token Verification:** All REST endpoints (`/api/status`, `/api/prompt`, `/api/context`, `/api/diff`, `/api/symbols`) enforce session authentication.
- **Automated Secret & Key Sanitization:**
  - High-risk files (`.env`, `.env.local`, `id_rsa`, `.pem`, `.key`) are strictly excluded from context outputs.
  - Regex secret sanitizers scan outgoing prompts to redact tokens, connection strings, and passwords.
- **Shadow DOM Encapsulation:** The floating in-chat widget runs in an isolated Shadow Root (`attachShadow({ mode: 'open' })`), preventing CSS collisions with host websites.

---

## 6. Troubleshooting & Diagnostics

### 1. Status dot is red / amber (Disconnected)
- Ensure the daemon is running: `continuum serve`.
- If running on a non-default port, update the daemon URL in the companion settings.
- Verify loopback connectivity: `curl http://127.0.0.1:8765/api/status`.

### 2. Send button not enabled after context injection
- Ensure your browser is not blocking userscript input events.
- If the chat uses an unusual container, the companion automatically falls back to copying the full prompt payload to your system clipboard.

### 3. Port conflict (EADDRINUSE)
- Project Continuum automatically scans and binds to the next sequential available port (e.g. `8766`, `8767`) if `8765` is busy.
