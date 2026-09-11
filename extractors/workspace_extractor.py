"""
Project Continuum - Workspace & Source Code Evidence Extractor
==============================================================
Milestone 2 - Phase 1: Physical Workspace & Source Code Inspection.
Scans the project directory, classifies files, detects programming languages,
runs language parsers to extract AST symbols and TODO markers, handles malformed
files gracefully, and produces canonical Evidence records.
"""

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from core.enums import EvidenceType, Status
from core.evidence import Evidence
from core.state_models import (
    AstSymbol,
    CanonicalProjectState,
    ProjectState,
)
from extractors.base import (
    CONFIG_FILE_NAMES,
    DEFAULT_IGNORE_DIRS,
    DOC_EXTENSIONS,
    BaseEvidenceExtractor,
)
from extractors.parsers.base import ILanguageParser, ParserResult
from extractors.parsers.js_ts_parser import JavaScriptTypeScriptParser
from extractors.parsers.python_parser import PythonParser


class WorkspaceEvidenceExtractor(BaseEvidenceExtractor):
    """
    Primary extractor for Phase 1.
    Performs physical filesystem scanning, language detection, and symbol parsing.
    """

    def __init__(self, custom_parsers: Optional[List[ILanguageParser]] = None):
        # Register default language parsers
        self.parsers: Dict[str, ILanguageParser] = {}
        default_parsers = [PythonParser(), JavaScriptTypeScriptParser()]
        if custom_parsers:
            default_parsers.extend(custom_parsers)

        for parser in default_parsers:
            for ext in parser.supported_extensions:
                self.parsers[ext.lower()] = parser

    @property
    def extractor_name(self) -> str:
        return "WorkspaceEvidenceExtractor"

    @property
    def supported_evidence_types(self) -> List[EvidenceType]:
        return [
            EvidenceType.SOURCE_CODE,
            EvidenceType.AST_SYMBOL,
            EvidenceType.DOCUMENTATION,
            EvidenceType.CONFIG_FILE
        ]

    def can_extract(self, target_path_or_input: str) -> bool:
        path = Path(target_path_or_input)
        return path.exists() and path.is_dir()

    def extract(self, target_path_or_input: str, context: Optional[Dict[str, Any]] = None) -> List[Evidence]:
        """
        Scans workspace directory, parses files, and returns a list of canonical Evidence records.
        """
        root_path = Path(target_path_or_input).resolve()
        evidence_list: List[Evidence] = []

        scanned_files, lang_counts = self._scan_directory(root_path)

        # 1. Workspace Structure Evidence
        structure_payload = {
            "root_path": str(root_path),
            "total_files": len(scanned_files),
            "languages": dict(lang_counts),
            "file_list": [str(p.relative_to(root_path).as_posix()) for p in scanned_files]
        }
        evidence_list.append(self.create_evidence(
            evidence_type=EvidenceType.SOURCE_CODE,
            summary=f"Workspace structure scanned: {len(scanned_files)} files across {len(lang_counts)} languages",
            raw_payload=structure_payload,
            source_uri=str(root_path),
            locator="workspace:root"
        ))

        # 2. Parse Source Code Files & Generate Symbol Evidence
        for file_path in scanned_files:
            ext = file_path.suffix.lower()
            rel_path = file_path.relative_to(root_path).as_posix()

            if ext in self.parsers:
                parser = self.parsers[ext]
                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    continue

                parse_result = parser.parse_source(rel_path, content)

                # Record AST Symbol evidence
                if parse_result.symbols:
                    evidence_list.append(self.create_evidence(
                        evidence_type=EvidenceType.AST_SYMBOL,
                        summary=f"Extracted {len(parse_result.symbols)} symbols from {rel_path}",
                        raw_payload={
                            "file_path": rel_path,
                            "language": parse_result.language,
                            "symbols": [s.to_dict() for s in parse_result.symbols],
                            "imports": [i.to_dict() for i in parse_result.imports],
                            "exported_symbols": parse_result.exported_symbols,
                            "markers": [m.to_dict() for m in parse_result.markers],
                            "errors": [e.to_dict() for e in parse_result.errors]
                        },
                        source_uri=rel_path,
                        locator=f"file:{rel_path}"
                    ))
            # Record Documentation Evidence
            elif ext in DOC_EXTENSIONS:
                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    evidence_list.append(self.create_evidence(
                        evidence_type=EvidenceType.DOCUMENTATION,
                        summary=f"Documentation file {rel_path} ({len(content.splitlines())} lines)",
                        raw_payload={
                            "file_path": rel_path,
                            "content": content
                        },
                        source_uri=rel_path,
                        locator=f"doc:{rel_path}"
                    ))
                except Exception:
                    pass

        return evidence_list

    def populate_project_state(self, root_dir: str, canonical_state: CanonicalProjectState) -> ProjectState:
        """
        High-level convenience method: scans workspace, updates `canonical_state.project_state`,
        and registers all harvested evidence into `canonical_state.evidence_pool`.
        """
        root_path = Path(root_dir).resolve()
        evidence_list = self.extract(str(root_path))

        all_symbols: List[AstSymbol] = []
        all_markers: List[Dict[str, Any]] = []
        scanned_files: List[str] = []
        lang_counter = Counter()

        for ev in evidence_list:
            canonical_state.add_evidence(ev)

            if ev.type == EvidenceType.SOURCE_CODE:
                scanned_files = ev.raw_payload.get("file_list", [])
                for lang, count in ev.raw_payload.get("languages", {}).items():
                    lang_counter[lang] += count
            elif ev.type == EvidenceType.AST_SYMBOL:
                for s_dict in ev.raw_payload.get("symbols", []):
                    sym = AstSymbol.from_dict(s_dict)
                    sym.evidence_id = ev.id
                    all_symbols.append(sym)
                all_markers.extend(ev.raw_payload.get("markers", []))

        # Update ProjectState
        ps = canonical_state.project_state
        ps.root_path = str(root_path)
        ps.files = scanned_files
        ps.detected_languages = [lang for lang, _ in lang_counter.most_common()]
        ps.symbols = all_symbols
        ps.todo_markers = all_markers
        ps.evidence_ids = [ev.id for ev in evidence_list]

        return ps

    def _scan_directory(self, root_path: Path) -> tuple[List[Path], Counter]:
        """Recursively traverses directory ignoring standard irrelevant folders."""
        scanned_files: List[Path] = []
        lang_counter = Counter()

        for path in sorted(root_path.rglob("*")):
            if path.is_file():
                # Check if any parent part is in ignored list
                parts = set(path.relative_to(root_path).parts)
                if any(ignored in parts for ignored in DEFAULT_IGNORE_DIRS):
                    continue

                scanned_files.append(path)
                ext = path.suffix.lower()
                lang = self._classify_extension(ext, path.name)
                if lang:
                    lang_counter[lang] += 1

        return scanned_files, lang_counter

    def _classify_extension(self, ext: str, filename: str) -> Optional[str]:
        if filename in CONFIG_FILE_NAMES:
            return "Configuration"
        if ext in {".py", ".pyw"}:
            return "Python"
        if ext in {".js", ".jsx", ".mjs", ".cjs"}:
            return "JavaScript"
        if ext in {".ts", ".tsx"}:
            return "TypeScript"
        if ext in {".go"}:
            return "Go"
        if ext in {".rs"}:
            return "Rust"
        if ext in {".java"}:
            return "Java"
        if ext in {".c", ".h"}:
            return "C"
        if ext in {".cpp", ".hpp", ".cc"}:
            return "C++"
        if ext in {".dart"}:
            return "Dart"
        if ext in DOC_EXTENSIONS:
            return "Documentation"
        return None
