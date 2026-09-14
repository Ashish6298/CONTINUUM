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


class ContinuumApiHandler(BaseHTTPRequestHandler):
    """
    HTTP Request Handler exposing Continuum REST API endpoints:
    - GET  /api/status
    - GET  /api/context
    - GET  /api/symbols
    - GET  /api/diff
    - POST /api/prompt
    """

    # Static configuration shared across handler threads
    workspace_root: Path = Path(".").resolve()
    auth_manager: Optional[SessionAuthManager] = None
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
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")

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
        """Serializes and sends a JSON response payload."""
        self._set_headers(status_code, "application/json")
        encoded = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
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
        """Dispatches GET requests to appropriate endpoint handlers."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = urllib.parse.parse_qs(parsed.query)

        if not path:
            path = "/"

        # Allow unauthenticated health check on root/status if require_auth is False,
        # but sensitive endpoints always enforce _validate_request_security
        if path in ("/", "/health"):
            self.handle_get_health()
            return

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
            else:
                self._send_error_response(f"Endpoint not found: {path}", status_code=404)
        except Exception as e:
            self._send_error_response(f"Internal server error: {str(e)}", status_code=500, details=traceback.format_exc())

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
            else:
                self._send_error_response(f"Endpoint not found: {path}", status_code=404)
        except Exception as e:
            self._send_error_response(f"Internal server error: {str(e)}", status_code=500, details=traceback.format_exc())

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
        Executes canonical workspace analysis and returns structured project evidence,
        detected languages, framework metadata, and token budgets.
        """
        pipeline = ContinuumPipeline(self.workspace_root)
        state, summary, _ = pipeline.run_full_analysis()

        # Calculate estimated character and token counts
        char_count = 0
        for f_rel in state.project_state.files:
            f_abs = self.workspace_root / f_rel
            if f_abs.is_file():
                try:
                    char_count += f_abs.stat().st_size
                except OSError:
                    pass

        estimated_tokens = int(char_count / 3.8) if char_count else 0

        payload = {
            "project_id": state.project_id,
            "workspace_root": str(self.workspace_root),
            "summary": summary.to_dict(),
            "confidence_score": summary.project_confidence,
            "languages": summary.languages_detected,
            "total_files": len(state.project_state.files),
            "total_symbols": len(state.project_state.symbols),
            "contradictions_count": len(state.contradictions),
            "token_budget_estimation": {
                "total_source_characters": char_count,
                "estimated_tokens": estimated_tokens,
                "gpt4o_percent_budget": round((estimated_tokens / 128000) * 100, 2),
                "claude35_percent_budget": round((estimated_tokens / 200000) * 100, 2),
                "gemini_percent_budget": round((estimated_tokens / 1000000) * 100, 4)
            },
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

                    if file_filter and sym_file != file_filter:
                        continue
                    if type_filter and sym_type != type_filter:
                        continue

                    symbols_data.append(sym)

        payload = {
            "workspace_root": str(self.workspace_root),
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
        include_verification: bool = req_data.get("include_verification", True)

        # Map target model
        model_map = {
            "claude": TargetModel.CLAUDE,
            "gpt": TargetModel.CODEX_GPT,
            "codex": TargetModel.CODEX_GPT,
            "gemini": TargetModel.GEMINI,
            "local": TargetModel.LOCAL_LLM,
            "universal": TargetModel.UNIVERSAL
        }
        target_model = model_map.get(target_model_str, TargetModel.UNIVERSAL)

        # Run pipeline analysis
        pipeline = ContinuumPipeline(self.workspace_root)
        state, _, _ = pipeline.run_full_analysis(
            task_description=task_description,
            token_budget=token_budget
        )

        # Apply custom file filtering if requested
        if selected_files is not None:
            norm_selected = {Path(f).as_posix() for f in selected_files}
            state.project_state.files = [
                f for f in state.project_state.files
                if Path(f).as_posix() in norm_selected
            ]

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
            "target_model": target_model_str,
            "task_description": task_description,
            "estimated_tokens": estimated_tokens,
            "prompt": handoff_doc,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self._send_json_response(payload)
