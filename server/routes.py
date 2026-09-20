"""
Project Continuum - REST API Handlers & Route Dispatcher
=========================================================
Milestone 25 - Phase 26: REST API Endpoints & Live Workspace Handlers.
Exposes Continuum analysis, symbols, diffs, and prompt generation over HTTP.
"""

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import sys
import traceback
from typing import Any, Dict, List, Optional
import urllib.parse

from core.enums import TargetModel
from core.state_models import CanonicalProjectState
from extractors.git_extractor import GitEvidenceExtractor
from extractors.workspace_extractor import WorkspaceEvidenceExtractor
from handoff.packager import UniversalHandoffPackager
from handoff.adapters import get_adapter_for_model
from pipeline.orchestrator import ContinuumPipeline
from storage.manager import ContinuumStorageManager


from server.auth import CorsOriginGuard, SessionAuthManager
from server.sanitizer import DaemonSanitizer
from server.static_manager import StaticAssetManager


class ContinuumApiHandler(BaseHTTPRequestHandler):
    """
    HTTP Request Handler exposing Continuum REST API endpoints and embedded Web Dashboard:
    - GET  / (and static assets /dashboard.css, /dashboard.js, etc.)
    - GET  /api/status
    - GET  /api/context
    - GET  /api/symbols
    - GET  /api/diff
    - POST /api/prompt
    """

    # Static configuration shared across handler threads
    workspace_root: Path = Path(".").resolve()
    auth_manager: Optional[SessionAuthManager] = None
    static_manager: StaticAssetManager = StaticAssetManager()
    require_auth: bool = True
    server_started_at: str = datetime.now(timezone.utc).isoformat()
    version: str = "1.2.0-dev"

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress standard noisy console logging for clean CLI output."""
        pass

    def _get_origin(self) -> Optional[str]:
        """Extracts the Origin or Referer header from the incoming request."""
        origin = self.headers.get("Origin")
        if not origin:
            referer = self.headers.get("Referer")
            if referer:
                parsed_ref = urllib.parse.urlparse(referer)
                if parsed_ref.scheme and parsed_ref.netloc:
                    origin = f"{parsed_ref.scheme}://{parsed_ref.netloc}"
        return origin

    def _set_headers(self, status_code: int = 200, content_type: str = "application/json") -> None:
        """Sets standard HTTP response headers with strict CORS validation."""
        self.send_response(status_code)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if "charset" not in content_type and "text" in content_type else content_type)

        # Apply strict CORS headers based on validated origin
        origin = self._get_origin()
        cors_headers = CorsOriginGuard.get_cors_headers(origin)
        for header_name, header_value in cors_headers.items():
            self.send_header(header_name, header_value)

        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()

    def do_OPTIONS(self) -> None:
        """Handles CORS preflight requests with origin verification."""
        origin = self._get_origin()
        if origin and not CorsOriginGuard.is_origin_allowed(origin):
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"CORS Origin '{origin}' is not permitted."}).encode("utf-8"))
            return

        self._set_headers(204)

    def _validate_request_security(self, query: Dict[str, List[str]]) -> bool:
        """
        Validates incoming request origin and authentication token.
        Returns True if authorized, False otherwise (and sends error response).
        """
        # 1. CORS Origin Guard Validation
        origin = self._get_origin()
        if origin and not CorsOriginGuard.is_origin_allowed(origin):
            self._send_error_response(
                f"Forbidden: Origin '{origin}' is not permitted to access local Continuum daemon.",
                status_code=403
            )
            return False

        # 2. Ephemeral Session Token Verification
        if self.require_auth and self.auth_manager:
            # Check Header first: X-Continuum-Token or Authorization: Bearer <token>
            token = self.headers.get("X-Continuum-Token")
            if not token:
                auth_header = self.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:].strip()

            # Check Query Param fallback: ?token=...
            if not token:
                token = query.get("token", [None])[0]

            if not token or not self.auth_manager.verify_token(token):
                self._send_error_response(
                    "Unauthorized: Missing or invalid X-Continuum-Token handshake secret.",
                    status_code=401
                )
                return False

        return True

    def _send_json_response(self, data: Any, status_code: int = 200) -> None:
        """Serializes and sends a sanitized JSON response payload."""
        self._set_headers(status_code, "application/json")
        # Apply secret redaction and path relative normalization
        sanitized_data = DaemonSanitizer.sanitize_payload(data, workspace_root=self.workspace_root)
        encoded = json.dumps(sanitized_data, indent=2, ensure_ascii=False).encode("utf-8")
        self.wfile.write(encoded)

    def _send_error_response(self, message: str, status_code: int = 400, details: Optional[Any] = None) -> None:
        """Sends a standardized JSON error response."""
        error_payload = {
            "error": message,
            "status_code": status_code,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        if details is not None:
            error_payload["details"] = details
        self._send_json_response(error_payload, status_code=status_code)

    def do_GET(self) -> None:
        """Dispatches GET requests to API routes or static SPA assets."""
        parsed = urllib.parse.urlparse(self.path)
        raw_path = parsed.path
        path = raw_path.rstrip("/")
        query = urllib.parse.parse_qs(parsed.query)

        if not path:
            path = "/"

        # 1. Check API endpoints first
        if path.startswith("/api/"):
            if not self._validate_request_security(query):
                return
            try:
                if path in ("/api/status", "/status"):
                    self.handle_get_status()
                elif path == "/api/context":
                    self.handle_get_context(query)
                elif path == "/api/symbols":
                    self.handle_get_symbols(query)
                elif path == "/api/diff":
                    self.handle_get_diff()
                elif path == "/api/checkpoints":
                    self.handle_get_checkpoints()
                else:
                    self._send_error_response(f"Endpoint not found: {path}", status_code=404)
            except Exception as e:
                self._send_error_response(f"Internal server error: {str(e)}", status_code=500, details=traceback.format_exc())
            return

        # 2. Public health check
        if path == "/health":
            self.handle_get_health()
            return

        if path == "/api/open-extensions":
            import webbrowser
            ext_url = "chrome://extensions/?id=dhdgffkkebhmkfjojejmpbldmpobfkfo"
            try:
                webbrowser.open(ext_url)
            except Exception:
                pass
            self._send_json_response({"status": "opened", "url": ext_url})
            return

        # 3. Public browser companion userscript distribution (/continuum.user.js and /install)
        if path == "/continuum.user.js":
            userjs_path = Path(__file__).parent.parent / "browser" / "continuum.user.js"
            if userjs_path.is_file():
                content = userjs_path.read_text(encoding="utf-8")
                if self.auth_manager:
                    token = self.auth_manager.get_token() or ""
                    if token:
                        content = content.replace(
                            "defaultToken: '',",
                            f"defaultToken: '{token}',"
                        )
                self._set_headers(200, "application/javascript; charset=utf-8")
                self.wfile.write(content.encode("utf-8"))
                return

        if path in ("/install", "/install.html"):
            token = (self.auth_manager.get_token() if self.auth_manager else "") or ""
            install_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Continuum — Browser Companion Setup</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0b0f19; color: #f8fafc; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 24px; box-sizing: border-box; }}
    .card {{ background: rgba(17, 24, 39, 0.95); border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 16px; padding: 36px; max-width: 580px; width: 100%; text-align: center; box-shadow: 0 24px 64px rgba(0, 0, 0, 0.6); }}
    .logo {{ font-size: 36px; color: #818cf8; margin-bottom: 6px; }}
    h1 {{ font-size: 22px; margin: 0 0 10px 0; }}
    p {{ color: #94a3b8; font-size: 13.5px; line-height: 1.5; margin: 0 0 20px 0; }}
    
    .alert-box {{
      background: rgba(245, 158, 11, 0.12);
      border: 1px solid rgba(245, 158, 11, 0.35);
      border-radius: 12px;
      padding: 16px;
      text-align: left;
      font-size: 13px;
      line-height: 1.5;
      margin-bottom: 22px;
      color: #fde68a;
    }}
    .alert-box strong {{ color: #fef08a; display: block; margin-bottom: 4px; font-size: 14px; }}
    .alert-box code {{ background: rgba(0,0,0,0.3); padding: 2px 6px; border-radius: 4px; color: #fff; font-family: monospace; }}

    .btn {{ display: inline-flex; align-items: center; justify-content: center; gap: 8px; width: 100%; box-sizing: border-box; font-weight: 700; font-size: 15px; padding: 14px 20px; border-radius: 10px; text-decoration: none; cursor: pointer; transition: transform .15s, opacity .15s; border: none; margin-bottom: 12px; }}
    .btn:hover {{ transform: translateY(-2px); opacity: 0.95; }}
    .btn-primary {{ background: linear-gradient(135deg, #6366f1, #4f46e5); color: #fff; box-shadow: 0 8px 24px rgba(99, 102, 241, 0.35); }}
    .btn-warning {{ background: linear-gradient(135deg, #d97706, #b45309); color: #fff; font-size: 14px; box-shadow: 0 6px 18px rgba(217, 119, 6, 0.35); }}
    .btn-secondary {{ background: rgba(255, 255, 255, 0.08); color: #cbd5e1; border: 1px solid rgba(255, 255, 255, 0.12); font-size: 13px; font-weight: 600; padding: 11px; }}
    .btn-secondary:hover {{ background: rgba(255, 255, 255, 0.14); color: #fff; }}
    
    .steps {{ text-align: left; background: rgba(10, 15, 28, 0.7); border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; padding: 16px 20px; font-size: 13px; color: #cbd5e1; margin-top: 16px; }}
    .steps ol {{ margin: 0; padding-left: 20px; }}
    .steps li {{ margin-bottom: 8px; }}
    .steps li:last-child {{ margin-bottom: 0; }}
    .toast {{ position: fixed; top: 20px; right: 20px; background: #10b981; color: #fff; padding: 12px 18px; border-radius: 8px; font-weight: 600; font-size: 13px; display: none; box-shadow: 0 8px 24px rgba(0,0,0,0.5); }}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">&#x2B22;</div>
    <h1>Continuum AI Companion Setup</h1>
    <p>Enable 1-click cross-model handoff (ChatGPT &rarr; Claude &rarr; Gemini) with zero context loss.</p>

    <div class="alert-box">
      <strong>&#x26A0;&#xFE0F; Step 1: Enable Browser Permission (Chrome & Brave)</strong>
      Chromium requires enabling <strong>Allow User Scripts</strong> in extension settings:
      <div style="margin: 10px 0; background: rgba(0,0,0,0.35); padding: 10px 12px; border-radius: 8px; font-family: monospace; font-size: 12.5px; word-break: break-all; color: #fff; display: flex; align-items: center; justify-content: space-between; gap: 8px;">
        <span>chrome://extensions/?id=dhdgffkkebhmkfjojejmpbldmpobfkfo</span>
        <button onclick="copyExtAddress()" style="background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.25); color: #fff; padding: 4px 8px; border-radius: 4px; cursor: pointer; font-size: 11px; white-space: nowrap;">
          &#x1F4CB; Copy
        </button>
      </div>
      <ol style="margin: 6px 0 0 16px; padding: 0; font-size: 12.5px; color: #fef3c7; line-height: 1.6;">
        <li>Copy the URL above and paste it into a <strong>new tab</strong>.</li>
        <li>Scroll down to <strong>Allow User Scripts</strong> and toggle it <strong>ON</strong>.</li>
      </ol>
    </div>

    <div style="margin-bottom: 6px; font-size: 13px; font-weight: 600; color: #cbd5e1; text-align: left;">
      Step 2: Install Companion Script
    </div>

    <a class="btn btn-primary" href="/continuum.user.js?token={token}">
      &#x26A1; 1-Click Install / Update Script
    </a>

    <button class="btn btn-secondary" onclick="copyScript()">
      &#x1F4CB; Copy Script to Clipboard (Fallback)
    </button>

    <div class="steps">
      <strong>How to Use Continuum Handoff:</strong>
      <ol>
        <li>Open <strong><a href="https://chatgpt.com" target="_blank" style="color:#818cf8;">chatgpt.com</a></strong> or <strong><a href="https://claude.ai" target="_blank" style="color:#818cf8;">claude.ai</a></strong>.</li>
        <li>Press <strong>Alt + C</strong> (or click <strong>&#x2B22; Continuum</strong> in bottom-right corner).</li>
        <li>Click <strong>Claude &rarr;</strong> to continue your conversation with full context and verified code!</li>
      </ol>
    </div>
  </div>
  <div class="toast" id="toast">&#x2713; Script copied to clipboard! Paste into Tampermonkey if needed.</div>

  <script>
    function copyExtAddress() {{
      const extUrl = 'chrome://extensions/?id=dhdgffkkebhmkfjojejmpbldmpobfkfo';
      navigator.clipboard.writeText(extUrl).catch(() => {{}});
      const t = document.getElementById('toast');
      t.innerHTML = '&#x1F4CB; Address copied! Open a new tab, paste, and turn ON "Allow User Scripts".';
      t.style.display = 'block';
      setTimeout(() => {{ t.style.display = 'none'; }}, 5000);
    }}

    async function copyScript() {{
      try {{
        const res = await fetch('/continuum.user.js?token={token}');
        const text = await res.text();
        await navigator.clipboard.writeText(text);
        const t = document.getElementById('toast');
        t.innerHTML = '&#x2713; Script copied to clipboard! Paste into Tampermonkey if needed.';
        t.style.display = 'block';
        setTimeout(() => {{ t.style.display = 'none'; }}, 3000);
      }} catch (e) {{
        alert('Could not copy automatically: ' + e);
      }}
    }}
  </script>
</body>
</html>"""
            self._set_headers(200, "text/html; charset=utf-8")
            self.wfile.write(install_html.encode("utf-8"))
            return

        # 4. Static assets serving for Web Dashboard SPA (index.html, dashboard.css, dashboard.js, etc.)
        asset_result = self.static_manager.resolve_asset(raw_path)
        if asset_result is not None:
            content, mime_type = asset_result
            # Automatically bootstrap session token into index.html
            if "text/html" in mime_type and self.auth_manager:
                token = self.auth_manager.get_token() or ""
                if token:
                    html_str = content.decode("utf-8", errors="replace")
                    bootstrap_script = f"<script>window.__CONTINUUM_SESSION_TOKEN__ = '{token}'; try {{ localStorage.setItem('continuum_token', '{token}'); }} catch(e){{}}</script></head>"
                    html_str = html_str.replace("</head>", bootstrap_script)
                    content = html_str.encode("utf-8")
            self._set_headers(200, mime_type)
            self.wfile.write(content)
            return

        # 4. Fallback 404
        self._send_error_response(f"Not found: {path}", status_code=404)


    def do_POST(self) -> None:
        """Dispatches POST requests to appropriate endpoint handlers."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = urllib.parse.parse_qs(parsed.query)

        if not self._validate_request_security(query):
            return

        try:
            if path == "/api/prompt":
                self.handle_post_prompt()
            elif path == "/api/workspace/sync":
                self.handle_post_workspace_sync()
            elif path == "/api/checkpoints":
                self.handle_post_checkpoint()
            else:
                self._send_error_response(f"Endpoint not found: {path}", status_code=404)
        except Exception as e:
            self._send_error_response(f"Internal server error: {str(e)}", status_code=500, details=traceback.format_exc())

    def handle_get_checkpoints(self) -> None:
        """GET /api/checkpoints - List all recorded handoff checkpoints."""
        from core.state_models import HandoffCheckpointManager
        mgr = HandoffCheckpointManager(str(self.workspace_root))
        checkpoints = mgr.list_checkpoints()
        self._send_json_response({
            "status": "success",
            "count": len(checkpoints),
            "checkpoints": [c.to_dict() for c in checkpoints],
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def handle_post_checkpoint(self) -> None:
        """POST /api/checkpoints - Record an immutable handoff checkpoint."""
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len == 0:
            self._send_error_response("Request body must not be empty.", status_code=400)
            return

        body_raw = self.rfile.read(content_len).decode("utf-8")
        try:
            data = json.loads(body_raw)
        except Exception:
            self._send_error_response("Malformed JSON body.", status_code=400)
            return

        from core.state_models import HandoffCheckpoint, HandoffCheckpointManager
        checkpoint_id = data.get("checkpoint_id") or uuid.uuid4().hex[:12]
        checkpoint = HandoffCheckpoint(
            checkpoint_id=checkpoint_id,
            origin_model=data.get("origin_model", "unknown"),
            target_model=data.get("target_model", "unknown"),
            timestamp=data.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            prompt_summary=data.get("prompt_summary", ""),
            compressed_prompt=data.get("compressed_prompt", ""),
            total_messages=int(data.get("total_messages", 0)),
            total_code_blocks=int(data.get("total_code_blocks", 0)),
            parent_checkpoint_id=data.get("parent_checkpoint_id"),
            metadata=data.get("metadata", {})
        )
        mgr = HandoffCheckpointManager(str(self.workspace_root))
        saved_path = mgr.record_checkpoint(checkpoint)
        self._send_json_response({
            "status": "success",
            "message": f"Checkpoint {checkpoint_id} recorded successfully.",
            "checkpoint": checkpoint.to_dict(),
            "file": str(saved_path.name),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def handle_post_workspace_sync(self) -> None:
        """
        POST /api/workspace/sync (Phase 44)
        Receives structured file patch payload from browser companion:
        {
          "files": [
            { "path": "server/auth.py", "content": "..." }
          ],
          "create_backup": true,
          "source": "chatgpt"
        }
        Applies atomic write with directory creation, path traversal defense,
        automatic safety backups in .continuum/backup/, and returns sync stats.
        """
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len == 0:
            self._send_error_response("Request body must not be empty.", status_code=400)
            return

        body_raw = self.rfile.read(content_len).decode("utf-8")
        try:
            data = json.loads(body_raw)
        except Exception:
            self._send_error_response("Malformed JSON body.", status_code=400)
            return

        files_to_sync = data.get("files", [])
        if not isinstance(files_to_sync, list) or len(files_to_sync) == 0:
            self._send_error_response("Missing or empty 'files' list in request body.", status_code=400)
            return

        create_backup = bool(data.get("create_backup", True))
        source_model = str(data.get("source", "browser"))

        storage = ContinuumStorageManager(str(self.workspace_root))
        storage.initialize_storage()

        synced_files = []
        contradictions = []
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        for item in files_to_sync:
            rel_path_str = item.get("path", "").strip()
            new_content = item.get("content", "")

            if not rel_path_str:
                continue

            # Path Traversal Guard
            norm_rel = Path(rel_path_str).as_posix().lstrip("/\\")
            target_path = (self.workspace_root / norm_rel).resolve()

            try:
                target_path.relative_to(self.workspace_root.resolve())
            except ValueError:
                self._send_error_response(f"Security violation: path '{rel_path_str}' escapes workspace boundary.", status_code=400)
                return

            # Check if file existed previously
            existed = target_path.is_file()
            old_size = target_path.stat().st_size if existed else 0

            # Backup if existed
            backup_path_str = None
            if existed and create_backup:
                safe_name = norm_rel.replace("/", "_").replace("\\", "_")
                backup_dest = storage.backup_dir / f"{safe_name}_{ts_str}.bak"
                import shutil
                shutil.copy2(target_path, backup_dest)
                backup_path_str = str(backup_dest.relative_to(self.workspace_root.resolve()))

            # Ensure parent directories exist
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Atomic Write via temporary file
            temp_path = target_path.with_suffix(target_path.suffix + f".tmp_{os.getpid()}_{ts_str}")
            temp_path.write_text(new_content, encoding="utf-8")
            temp_path.replace(target_path)

            synced_files.append({
                "path": norm_rel,
                "status": "updated" if existed else "created",
                "bytes_written": len(new_content.encode("utf-8")),
                "backup": backup_path_str
            })

        response_payload = {
            "status": "success",
            "message": f"Successfully synced {len(synced_files)} file(s) from {source_model} to workspace.",
            "source": source_model,
            "synced_count": len(synced_files),
            "files": synced_files,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self._send_json_response(response_payload)

    # --------------------------------------------------------------------------
    # 0. GET /health
    # --------------------------------------------------------------------------
    def handle_get_health(self) -> None:
        """Public minimal health check."""
        payload = {
            "status": "online",
            "system": "Continuum HTTP Daemon",
            "version": self.version,
            "requires_auth": self.require_auth,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self._send_json_response(payload)

    # --------------------------------------------------------------------------
    # 1. GET /api/status
    # --------------------------------------------------------------------------
    def handle_get_status(self) -> None:
        """
        Returns daemon status, Continuum version, workspace root path, active git
        branch, and server uptime.
        """
        git_extractor = GitEvidenceExtractor()
        branch = None
        head_commit = None
        is_git = git_extractor.is_git_repository(self.workspace_root)
        if is_git:
            branch, head_commit = git_extractor.get_head_info(self.workspace_root)

        payload = {
            "status": "online",
            "system": "Continuum HTTP Daemon",
            "version": self.version,
            "workspace_root": str(self.workspace_root),
            "is_git_repository": is_git,
            "git_branch": branch,
            "git_head_commit": head_commit,
            "server_started_at": self.server_started_at,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self._send_json_response(payload)

    # --------------------------------------------------------------------------
    # 2. GET /api/context
    # --------------------------------------------------------------------------
    def handle_get_context(self, query: Dict[str, List[str]]) -> None:
        """
        Returns structured project evidence, detected languages, framework metadata,
        and token budgets. Loads from cached .continuum/state.json for speed.
        Pass ?refresh=1 to force a fresh full pipeline scan.
        Filters out high-risk files (.env, *.key, etc.).
        """
        force_refresh = query.get("refresh", ["0"])[0] in ("1", "true", "yes")
        storage = ContinuumStorageManager(str(self.workspace_root))

        if not force_refresh and storage.state_exists():
            # Fast path: load from saved .continuum/state.json (~10ms vs 25s)
            try:
                canonical = storage.load_state(validate=False)
                state_obj = type('obj', (object,), {
                    'project_id': canonical.project_id,
                    'project_state': canonical.project_state,
                    'contradictions': canonical.contradictions,
                    'graph_nodes': canonical.graph_nodes,
                })()
                raw_langs = canonical.project_state.detected_languages or []
                all_files = canonical.project_state.files or []
                symbols = canonical.project_state.symbols or []

                safe_files = [f for f in all_files if not DaemonSanitizer.is_high_risk_file(f)]

                char_count = 0
                lines_of_code = 0
                for f_rel in safe_files:
                    f_abs = self.workspace_root / f_rel
                    if f_abs.is_file():
                        try:
                            char_count += f_abs.stat().st_size
                            with open(f_abs, "r", encoding="utf-8", errors="ignore") as fp:
                                lines_of_code += sum(1 for _ in fp)
                        except OSError:
                            pass

                estimated_tokens = int(char_count / 3.8) if char_count else 0
                if isinstance(raw_langs, dict):
                    languages_dict = raw_langs
                elif isinstance(raw_langs, list):
                    languages_dict = {lang: 1 for lang in raw_langs}
                else:
                    languages_dict = {}

                payload = {
                    "project_id": canonical.project_id,
                    "workspace_root": str(self.workspace_root),
                    "files": safe_files,
                    "summary": {"languages_detected": raw_langs},
                    "confidence_score": 0.9,
                    "languages": languages_dict,
                    "total_files": len(safe_files),
                    "lines_of_code": lines_of_code,
                    "total_symbols": len(symbols),
                    "contradictions_count": len(canonical.contradictions),
                    "token_budget_estimation": {
                        "total_source_characters": char_count,
                        "estimated_tokens": estimated_tokens,
                        "gpt4o_percent_budget": round((estimated_tokens / 128000) * 100, 2),
                        "claude35_percent_budget": round((estimated_tokens / 200000) * 100, 2),
                        "gemini_percent_budget": round((estimated_tokens / 1000000) * 100, 4)
                    },
                    "cached": True,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                self._send_json_response(payload)
                return
            except Exception:
                pass  # Fall through to full pipeline scan on error

        # Full pipeline scan (slow, ~25s) - used on first load or ?refresh=1
        pipeline = ContinuumPipeline(self.workspace_root)
        state, summary, _ = pipeline.run_full_analysis()

        # Persist state for next fast-path load
        try:
            storage.initialize_storage()
            storage.save_state(state)
        except Exception:
            pass

        safe_files = [f for f in state.project_state.files if not DaemonSanitizer.is_high_risk_file(f)]
        state.project_state.files = safe_files

        char_count = 0
        lines_of_code = 0
        for f_rel in safe_files:
            f_abs = self.workspace_root / f_rel
            if f_abs.is_file():
                try:
                    char_count += f_abs.stat().st_size
                    with open(f_abs, "r", encoding="utf-8", errors="ignore") as fp:
                        lines_of_code += sum(1 for _ in fp)
                except OSError:
                    pass

        estimated_tokens = int(char_count / 3.8) if char_count else 0

        raw_langs = summary.languages_detected
        if isinstance(raw_langs, dict):
            languages_dict = raw_langs
        elif isinstance(raw_langs, list):
            languages_dict = {lang: 1 for lang in raw_langs}
        else:
            languages_dict = {}

        payload = {
            "project_id": state.project_id,
            "workspace_root": str(self.workspace_root),
            "files": safe_files,
            "summary": summary.to_dict(),
            "confidence_score": summary.project_confidence,
            "languages": languages_dict,
            "total_files": len(safe_files),
            "lines_of_code": lines_of_code,
            "total_symbols": len(state.project_state.symbols),
            "contradictions_count": len(state.contradictions),
            "token_budget_estimation": {
                "total_source_characters": char_count,
                "estimated_tokens": estimated_tokens,
                "gpt4o_percent_budget": round((estimated_tokens / 128000) * 100, 2),
                "claude35_percent_budget": round((estimated_tokens / 200000) * 100, 2),
                "gemini_percent_budget": round((estimated_tokens / 1000000) * 100, 4)
            },
            "cached": False,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self._send_json_response(payload)


    # --------------------------------------------------------------------------
    # 3. GET /api/symbols
    # --------------------------------------------------------------------------
    def handle_get_symbols(self, query: Dict[str, List[str]]) -> None:
        """
        Returns extracted AST symbols, exported functions, classes, and signatures
        using existing v1.0.0 symbol extractors.
        Filters out symbols from high-risk credential files.
        Query params:
        - `file`: Filter symbols belonging to a specific relative file path.
        - `type`: Filter symbols by type (function, class, method, interface).
        """
        file_filter = query.get("file", [None])[0]
        type_filter = query.get("type", [None])[0]

        ws_extractor = WorkspaceEvidenceExtractor()
        evidence_list = ws_extractor.extract(str(self.workspace_root))

        symbols_data: List[Dict[str, Any]] = []
        for ev in evidence_list:
            if ev.type.value == "AST_SYMBOL" and isinstance(ev.raw_payload, dict):
                symbols = ev.raw_payload.get("symbols", [])
                for sym in symbols:
                    sym_file = sym.get("file_path")
                    sym_type = sym.get("symbol_type")

                    if sym_file and DaemonSanitizer.is_high_risk_file(sym_file):
                        continue
                    if file_filter and sym_file != file_filter:
                        continue
                    if type_filter and sym_type != type_filter:
                        continue

                    # Sanitize symbol metadata and normalize file path
                    if sym_file:
                        sym["file_path"] = DaemonSanitizer.normalize_path(sym_file, self.workspace_root)

                    symbols_data.append(sym)

        payload = {
            "workspace_root": DaemonSanitizer.normalize_path(self.workspace_root, self.workspace_root),
            "total_symbols_found": len(symbols_data),
            "filters_applied": {
                "file": file_filter,
                "type": type_filter
            },
            "symbols": symbols_data,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self._send_json_response(payload)

    # --------------------------------------------------------------------------
    # 4. GET /api/diff
    # --------------------------------------------------------------------------
    def handle_get_diff(self) -> None:
        """
        Returns sanitized staged and unstaged Git diffs formatted for AI context.
        """
        git_extractor = GitEvidenceExtractor()
        if not git_extractor.is_git_repository(self.workspace_root):
            payload = {
                "is_git_repository": False,
                "staged_diff": "",
                "unstaged_diff": "",
                "full_diff": "",
                "status": "Workspace is not a Git repository."
            }
            self._send_json_response(payload)
            return

        status_data = git_extractor.get_working_tree_status(self.workspace_root)
        staged_diff = git_extractor.get_staged_diff(self.workspace_root)
        unstaged_diff = git_extractor.get_unstaged_diff(self.workspace_root)

        full_diff_parts = []
        if staged_diff:
            full_diff_parts.append(f"# STAGED CHANGES:\n{staged_diff}")
        if unstaged_diff:
            full_diff_parts.append(f"# UNSTAGED CHANGES:\n{unstaged_diff}")
        full_diff = "\n\n".join(full_diff_parts)

        payload = {
            "is_git_repository": True,
            "is_dirty": status_data.get("is_dirty", False),
            "staged_files": status_data.get("staged_files", []),
            "unstaged_files": status_data.get("unstaged_files", []),
            "untracked_files": status_data.get("untracked_files", []),
            "staged_diff": staged_diff,
            "unstaged_diff": unstaged_diff,
            "full_diff": full_diff,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self._send_json_response(payload)

    # --------------------------------------------------------------------------
    # 5. POST /api/prompt
    # --------------------------------------------------------------------------
    def handle_post_prompt(self) -> None:
        """
        Accepts filtering parameters (selected files, target model profile, token
        budget limit, diff inclusion, verification inclusion).
        Returns a fully assembled, optimized markdown/XML prompt payload ready for
        direct model consumption.
        """
        # Read request body
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self._send_error_response("Empty request body. JSON payload required.", status_code=400)
            return

        body_bytes = b""
        if hasattr(self, "rfile") and content_length > 0:
            body_bytes = self.rfile.read(content_length)

        try:
            req_data = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            self._send_error_response("Invalid JSON in request body.", status_code=400)
            return

        # Parse request options
        selected_files: Optional[List[str]] = req_data.get("files")
        target_model_str: str = req_data.get("target_model", "universal").lower()
        task_description: Optional[str] = req_data.get("task_description")
        token_budget: Optional[int] = req_data.get("token_budget")
        include_diff: bool = req_data.get("include_diff", True)
        include_symbols: bool = req_data.get("include_symbols", True)
        include_verification: bool = req_data.get("include_verification", True)

        # Map target model
        model_map = {
            "claude": TargetModel.CLAUDE,
            "gpt": TargetModel.CODEX_GPT,
            "chatgpt": TargetModel.CODEX_GPT,
            "codex": TargetModel.CODEX_GPT,
            "gemini": TargetModel.GEMINI,
            "aistudio": TargetModel.GEMINI,
            "local": TargetModel.LOCAL_LLM,
            "deepseek": TargetModel.LOCAL_LLM,
            "openllm": TargetModel.LOCAL_LLM,
            "universal": TargetModel.UNIVERSAL
        }
        target_model = model_map.get(target_model_str, TargetModel.UNIVERSAL)

        # Load state from cache (fast ~50ms) or run full pipeline scan if needed
        storage = ContinuumStorageManager(str(self.workspace_root))
        if storage.state_exists():
            try:
                state = storage.load_state(validate=False)
            except Exception:
                # Fall back to pipeline scan if state is corrupted
                pipeline = ContinuumPipeline(self.workspace_root)
                state, _, _ = pipeline.run_full_analysis(
                    task_description=task_description,
                    token_budget=token_budget
                )
        else:
            # No cached state - run pipeline and persist it
            pipeline = ContinuumPipeline(self.workspace_root)
            state, _, _ = pipeline.run_full_analysis(
                task_description=task_description,
                token_budget=token_budget
            )
            try:
                storage.initialize_storage()
                storage.save_state(state)
            except Exception:
                pass

        # Apply custom file filtering if requested
        if selected_files is not None and len(selected_files) > 0:
            norm_selected = {Path(f).as_posix() for f in selected_files}
            state.project_state.files = [
                f for f in state.project_state.files
                if Path(f).as_posix() in norm_selected
            ]
            # Filter symbols to selected files
            state.project_state.symbols = [
                s for s in state.project_state.symbols
                if Path(s.file_path).as_posix() in norm_selected
            ]
            # Filter graph nodes to only those belonging to selected files
            selected_sym_ids = {f"sym_{s.name}" for s in state.project_state.symbols}
            filtered_nodes = {}
            for nid, n in state.graph_nodes.items():
                if n.node_type.value in ("COMPONENT", "API", "AST_SYMBOL"):
                    if nid in selected_sym_ids or n.name in {s.name for s in state.project_state.symbols}:
                        filtered_nodes[nid] = n
                else:
                    filtered_nodes[nid] = n
            state.graph_nodes = filtered_nodes

        # Apply symbol toggle filtering
        if not include_symbols:
            state.project_state.symbols = []
            state.graph_nodes = {
                nid: n for nid, n in state.graph_nodes.items()
                if n.node_type.value != "AST_SYMBOL"
            }

        # Apply verification / test proof toggle filtering
        if not include_verification:
            state.project_state.test_results = []
            state.contradictions = []
            state.graph_nodes = {
                nid: n for nid, n in state.graph_nodes.items()
                if n.node_type.value != "TEST"
            }


        # Generate model-tailored handoff package
        adapter = get_adapter_for_model(target_model)
        handoff_files = adapter.generate_handoff(state)
        handoff_doc = handoff_files.get("handoff.md", "")
        if "project-context.md" in handoff_files:
            handoff_doc = handoff_files["project-context.md"] + "\n\n" + handoff_doc

        # Prepend task instruction if provided
        if task_description:
            handoff_doc = f"## 🎯 TASK OBJECTIVE: {task_description}\n\n" + handoff_doc

        # Append Git Diff if requested
        if include_diff:
            git_extractor = GitEvidenceExtractor()
            if git_extractor.is_git_repository(self.workspace_root):
                staged = git_extractor.get_staged_diff(self.workspace_root)
                unstaged = git_extractor.get_unstaged_diff(self.workspace_root)
                diff_block = []
                if staged:
                    diff_block.append(f"### STAGED DIFF\n```diff\n{staged}\n```")
                if unstaged:
                    diff_block.append(f"### UNSTAGED DIFF\n```diff\n{unstaged}\n```")
                if diff_block:
                    handoff_doc += "\n\n## 🌿 LIVE WORKSPACE DIFFS\n" + "\n\n".join(diff_block)

        estimated_tokens = int(len(handoff_doc) / 3.8)

        payload = {
            "status": "success",
            "target_model": target_model_str,
            "task_description": task_description,
            "estimated_tokens": estimated_tokens,
            "include_diff": include_diff,
            "include_symbols": include_symbols,
            "include_verification": include_verification,
            "prompt": handoff_doc,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self._send_json_response(payload)

