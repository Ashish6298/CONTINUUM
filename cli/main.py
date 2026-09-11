"""
Project Continuum - Command Line Interface (CLI)
=================================================
Milestone 7 - Phase 18: Continuum Daemon & CLI.
Provides standard developer commands:
- continuum init
- continuum status
- continuum scan
- continuum verify
- continuum graph
- continuum handoff
- continuum daemon
"""

import argparse
import json
import os
from pathlib import Path
import sys
from typing import List, Optional

# Ensure project root is on sys.path when executed directly as a script
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.enums import EvidenceType, Status, TargetModel
from core.state_models import CanonicalProjectState, ProjectState
from daemon.service import ContinuumDaemon
from extractors.workspace_extractor import WorkspaceEvidenceExtractor
from extractors.config_extractor import ConfigEvidenceExtractor
from extractors.git_extractor import GitEvidenceExtractor
from graph.manager import StateGraphManager
from handoff.packager import UniversalHandoffPackager
from handoff.adapters import get_adapter_for_model
from storage.manager import ContinuumStorageManager
from storage.hooks import GitHookManager
from storage.recovery import StateRecoveryManager


def build_parser() -> argparse.ArgumentParser:
    """Builds the Continuum CLI command argument parser."""
    parser = argparse.ArgumentParser(
        prog="continuum",
        description="Project Continuum — AI Work Continuity & Agent Handoff System"
    )
    parser.add_argument("--version", action="version", version="continuum v1.0.0 (Python 3.10+ | Schema 1.0.0)")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 1. init
    init_parser = subparsers.add_parser("init", help="Initialize .continuum storage and Git hooks in workspace")
    init_parser.add_argument("--path", default=".", help="Workspace path (default: current directory)")

    # 2. status
    status_parser = subparsers.add_parser("status", help="Print verified project state, contradictions, and next actions")
    status_parser.add_argument("--path", default=".", help="Workspace path")
    status_parser.add_argument("--json", action="store_true", help="Output status in JSON format")

    # 3. scan
    scan_parser = subparsers.add_parser("scan", help="Perform full workspace evidence extraction and update state")
    scan_parser.add_argument("--path", default=".", help="Workspace path")

    # 4. graph
    graph_parser = subparsers.add_parser("graph", help="Inspect Canonical State Graph (DAG)")
    graph_parser.add_argument("--path", default=".", help="Workspace path")
    graph_parser.add_argument("--mermaid", action="store_true", help="Export Mermaid diagram")
    graph_parser.add_argument("--stats", action="store_true", help="Show topological metrics")

    # 5. handoff
    handoff_parser = subparsers.add_parser("handoff", help="Generate AI handoff package")
    handoff_parser.add_argument("--path", default=".", help="Workspace path")
    handoff_parser.add_argument("--model", choices=["auto", "universal", "claude", "codex", "gpt", "gemini", "local"], default="auto", help="Target AI model format (default: auto omni-model)")
    handoff_parser.add_argument("--output-dir", default=None, help="Directory to save the handoff package (default: ./ai_handoff)")

    # 6. daemon
    daemon_parser = subparsers.add_parser("daemon", help="Manage background workspace observer daemon")
    daemon_parser.add_argument("action", choices=["start", "stop", "status", "run-once"], help="Daemon action to perform")
    daemon_parser.add_argument("--path", default=".", help="Workspace path")

    return parser


def handle_init(args: argparse.Namespace) -> int:
    ws = Path(args.path).resolve()
    storage = ContinuumStorageManager(str(ws))
    storage.initialize_storage()

    hooks = GitHookManager(str(ws))
    if hooks.is_git_repo():
        hook_res = hooks.install_hooks()
        print(f"[OK] Initialized Continuum storage at {storage.continuum_dir}")
        print(f"[OK] Installed Git hooks: post-commit={hook_res.get('post-commit')}, pre-commit={hook_res.get('pre-commit')}")
    else:
        print(f"[OK] Initialized Continuum storage at {storage.continuum_dir} (Non-git workspace)")

    return 0


def handle_status(args: argparse.Namespace) -> int:
    ws = Path(args.path).resolve()
    storage = ContinuumStorageManager(str(ws))

    if not storage.state_exists():
        print(f"[WARN] No active Continuum state found at {ws}. Run 'continuum scan' or 'continuum init' first.")
        return 1

    state = storage.load_state(validate=True)

    if getattr(args, "json", False):
        print(json.dumps(state.to_dict(), indent=2))
        return 0

    p_state = state.project_state
    c_state = state.conversational_state
    exec_state = state.agent_execution_state

    print("=" * 70)
    print(f"PROJECT CONTINUUM — VERIFIED PROJECT STATUS")
    print("=" * 70)
    print(f"Project ID:       {state.project_id} (Schema: {state.schema_version})")
    print(f"Workspace Root:   {p_state.root_path}")
    print(f"Source Files:     {len(p_state.files)} file(s)")
    print(f"AST Symbols:      {len(p_state.symbols)} symbol(s)")
    print(f"Build Status:     [{p_state.build_status.value}]")
    print(f"Graph Nodes:      {len(state.graph_nodes)} nodes, {len(state.graph_edges)} edges")
    print(f"Contradictions:   {len(state.contradictions)} discrepancy record(s)")

    if exec_state.next_action:
        na = exec_state.next_action
        print(f"\n[NEXT ACTION]     [{na.action_type}] {na.target_uri}")
        print(f"   Description:   {na.description}")
    print("=" * 70)
    return 0


def handle_scan(args: argparse.Namespace) -> int:
    ws = Path(args.path).resolve()
    storage = ContinuumStorageManager(str(ws))
    storage.initialize_storage()

    print(f"[SCAN] Scanning workspace at {ws}...")
    ws_extractor = WorkspaceEvidenceExtractor()
    ev_list = ws_extractor.extract(str(ws))

    # Construct canonical state from extracted evidence
    p_state = ProjectState(root_path=str(ws))
    for ev in ev_list:
        if ev.type == EvidenceType.SOURCE_CODE or ev.type.value == "SOURCE_CODE":
            files = ev.raw_payload.get("file_list", ev.raw_payload.get("files", []))
            p_state.files.extend(files)
            langs = list(ev.raw_payload.get("languages", {}).keys()) or ev.raw_payload.get("detected_languages", [])
            p_state.detected_languages.extend(langs)
        elif ev.type == EvidenceType.AST_SYMBOL or ev.type.value == "AST_SYMBOL":
            from core.state_models import AstSymbol
            sym_dicts = ev.raw_payload.get("symbols", [])
            for sd in sym_dicts:
                p_state.symbols.append(AstSymbol.from_dict(sd))

    state = CanonicalProjectState(
        project_id=f"proj_{ws.name}",
        project_state=p_state
    )

    # Build DAG
    graph_manager = StateGraphManager(state)
    graph_manager.build_from_canonical_state(state)

    storage.save_state(state, create_history_snapshot=True)
    print(f"[OK] Scan complete. Harvested {len(p_state.files)} files, {len(p_state.symbols)} symbols.")
    return 0


def handle_graph(args: argparse.Namespace) -> int:
    ws = Path(args.path).resolve()
    storage = ContinuumStorageManager(str(ws))
    if not storage.state_exists():
        print(f"[WARN] No active state. Run 'continuum scan' first.")
        return 1

    state = storage.load_state(validate=True)
    graph_manager = StateGraphManager(state)

    if getattr(args, "mermaid", False):
        print(graph_manager.export_mermaid())
        return 0

    if getattr(args, "stats", False):
        stats = graph_manager.get_stats()
        print(json.dumps(stats.to_dict(), indent=2))
        return 0

    # Default: summary
    stats = graph_manager.get_stats()
    print(f"Canonical State Graph: {stats.total_nodes} nodes, {stats.total_edges} edges.")
    for k, v in stats.nodes_by_type.items():
        print(f"  - {k}: {v}")
    return 0


def handle_handoff(args: argparse.Namespace) -> int:
    ws = Path(args.path).resolve()
    storage = ContinuumStorageManager(str(ws))
    
    # Auto-initialize and scan if not previously initialized (1-command magic)
    if not storage.state_exists():
        print(f"[AUTO] Initializing and scanning workspace at {ws}...")
        storage.initialize_storage()
        ws_extractor = WorkspaceEvidenceExtractor()
        config_extractor = ConfigEvidenceExtractor()
        git_extractor = GitEvidenceExtractor()
        
        state = CanonicalProjectState(schema_version="1.0.0", project_id=f"proj_{ws.name}")
        ws_extractor.populate_project_state(str(ws), state)
        config_extractor.populate_project_state(str(ws), state)
        git_extractor.populate_project_state(str(ws), state)
        storage.save_state(state)
        print(f"[OK] Workspace parsed: {len(state.project_state.files)} files, {len(state.project_state.symbols)} symbols.")
    else:
        state = storage.load_state(validate=True)
        
    model_choice = getattr(args, "model", "auto").lower()

    out_dir = args.output_dir or str(ws / "ai_handoff")
    out_path = Path(out_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    if model_choice in ("auto", "all", "universal"):
        # Auto mode: Generate Universal package + all model-specific profiles
        packager = UniversalHandoffPackager()
        pkg = packager.generate_package(state)
        paths = pkg.save_to_directory(str(out_path))

        # Also generate dedicated model views (claude_handoff.md, gpt_handoff.md, gemini_handoff.md)
        claude_adapter = get_adapter_for_model(TargetModel.CLAUDE)
        gpt_adapter = get_adapter_for_model(TargetModel.CODEX_GPT)
        gemini_adapter = get_adapter_for_model(TargetModel.GEMINI)

        (out_path / "claude_handoff.md").write_text(claude_adapter.generate_handoff(state)["handoff.md"], encoding="utf-8")
        (out_path / "gpt_handoff.md").write_text(gpt_adapter.generate_handoff(state)["handoff.md"], encoding="utf-8")
        (out_path / "gemini_handoff.md").write_text(gemini_adapter.generate_handoff(state)["handoff.md"], encoding="utf-8")

        output_text = f"""
◈ [HANDOFF READY] Generated Omni-Model Continuity Package:

  Location: {out_path}

   ✦ Universal Handoff  →  {out_path / 'handoff.md'} (Works for ANY model)

   ✦ Claude Optimized   →  {out_path / 'claude_handoff.md'}

   ✦ GPT / Codex Plan   →  {out_path / 'gpt_handoff.md'}

   ✦ Gemini Hierarchy   →  {out_path / 'gemini_handoff.md'}

   ✦ Machine State      →  {out_path / 'project-state.json'}

➤ [NEXT ACTION] Paste this prompt into your next AI Agent chat:

   "Read {out_path.name}/handoff.md and continue the project."

"""
        try:
            sys.stdout.buffer.write(output_text.encode("utf-8"))
            sys.stdout.buffer.flush()
        except Exception:
            print(output_text)
        return 0

    model_map = {
        "claude": TargetModel.CLAUDE,
        "codex": TargetModel.CODEX_GPT,
        "gpt": TargetModel.CODEX_GPT,
        "gemini": TargetModel.GEMINI,
        "local": TargetModel.LOCAL_LLM,
    }
    target_enum = model_map.get(model_choice, TargetModel.CODEX_GPT)
    adapter = get_adapter_for_model(target_enum)
    handoff_dict = adapter.generate_handoff(state)

    for fname, content in handoff_dict.items():
        (out_path / fname).write_text(content, encoding="utf-8")

    output_text = f"""
◈ [HANDOFF READY] Generated {target_enum.value} Continuity Package:

  Location: {out_path}

➤ [NEXT ACTION] Paste this prompt into your next AI Agent chat:

   "Read {out_path.name}/handoff.md and continue the project."

"""
    try:
        sys.stdout.buffer.write(output_text.encode("utf-8"))
        sys.stdout.buffer.flush()
    except Exception:
        print(output_text)

    return 0


def handle_daemon(args: argparse.Namespace) -> int:
    ws = Path(args.path).resolve()
    daemon = ContinuumDaemon(str(ws))

    if args.action == "start":
        status = daemon.start(run_in_background=True)
        print(f"[OK] Continuum daemon started in background (PID: {status.pid})")
        return 0
    elif args.action == "stop":
        status = daemon.stop()
        print(f"[OK] Continuum daemon stopped.")
        return 0
    elif args.action == "status":
        status = daemon.get_status()
        print(f"Continuum Daemon Status: {'RUNNING' if status.is_running else 'STOPPED'}")
        if status.pid:
            print(f"  PID: {status.pid}")
        print(f"  Cycles Completed: {status.cycles_completed}")
        print(f"  Changes Processed: {status.total_changes_processed}")
        return 0
    elif args.action == "run-once":
        res = daemon.run_once()
        print(f"[OK] Daemon single pass complete: {res}")
        return 0

    return 1


def print_welcome_hub() -> None:
    """Prints a solid, unbroken block-font terminal welcome hub."""
    version = "v1.0.0"
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    
    # Clean, unbroken block typography for "CONTINUUM" (Centered)
    banner_text = f"""
                 █▀▀ █▀█ █▄ █ ▀█▀ █ █▄ █ █ █ █ █ █▀▄▀█
                 █▄▄ █▄█ █ ▀█  █  █ █ ▀█ █▄█ █▄█ █ ▀ █

             AI Work Continuity & Cross-Model Agent Handoff System
  ─────────────────────────────────────────────────────────────────────────────

    The one-Command Workflow: $ continuum handoff

    Automatically captures your project state, extracts AST symbols,
    and generates a ready-to-use 'ai_handoff/' package for your next
    AI Agent (Claude, GPT, Gemini, Cursor, Antigravity, etc.)

  ─────────────────────────────────────────────────────────────────────────────
  {version}   python {py_version}   mit license   

"""
    try:
        sys.stdout.buffer.write(banner_text.encode("utf-8"))
        sys.stdout.buffer.flush()
    except Exception:
        print(banner_text)


def main(argv: Optional[List[str]] = None) -> int:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        print_welcome_hub()
        return 0

    handlers = {
        "init": handle_init,
        "status": handle_status,
        "scan": handle_scan,
        "graph": handle_graph,
        "handoff": handle_handoff,
        "daemon": handle_daemon,
    }

    handler = handlers.get(args.command)
    if handler:
        return handler(args)

    print_welcome_hub()
    return 1


if __name__ == "__main__":
    sys.exit(main())
