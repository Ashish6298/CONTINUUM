"""
Project Continuum - JavaScript & TypeScript Source Parser
=========================================================
Extracts classes, interfaces, types, functions, arrow functions,
imports, exports, and comments from JS/TS/JSX/TSX files.
"""

import re
from typing import List, Optional

from core.state_models import AstSymbol
from extractors.parsers.base import (
    ILanguageParser,
    ImportStatement,
    ParserResult
)
from extractors.parsers.comment_parser import CommentMarkerParser


class JavaScriptTypeScriptParser(ILanguageParser):
    """
    Parser for JavaScript and TypeScript source files.
    Extracts classes, interfaces, exported functions, arrow functions, and types.
    """

    @property
    def language_name(self) -> str:
        return "JavaScript/TypeScript"

    @property
    def supported_extensions(self) -> List[str]:
        return [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"]

    # Regex patterns for JS/TS structures
    IMPORT_PATTERN = re.compile(
        r"""(?:import\s+(?:(?:type\s+)?([\w*${}\s,]+)\s+from\s+)?['"]([^'"]+)['"]|require\(['"]([^'"]+)['"]\))"""
    )

    EXPORT_FUNC_PATTERN = re.compile(
        r"""(?:export\s+(?:default\s+)?)?(?:async\s+)?function(?:\s*\*|\s+)([\w$]+)\s*\(([^)]*)\)(?:\s*:\s*([\w<>\[\],\s]+))?"""
    )

    EXPORT_ARROW_PATTERN = re.compile(
        r"""(?:export\s+)?(?:const|let|var)\s+([\w$]+)(?:\s*:\s*[\w\.<>\[\],\s]+)?\s*=\s*(?:async\s*)?\(([^)]*)\)(?:\s*:\s*([\w\.<>\[\],\s]+))?\s*=>"""
    )

    CLASS_PATTERN = re.compile(
        r"""(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+([\w$]+)(?:\s+extends\s+([\w$]+))?(?:\s+implements\s+([\w$,\s]+))?"""
    )

    INTERFACE_PATTERN = re.compile(
        r"""(?:export\s+)?interface\s+([\w$]+)(?:\s+extends\s+([\w$,\s]+))?"""
    )

    TYPE_ALIAS_PATTERN = re.compile(
        r"""(?:export\s+)?type\s+([\w$]+)\s*="""
    )

    def parse_source(self, file_path: str, content: str) -> ParserResult:
        result = ParserResult(
            file_path=file_path,
            language=self.language_name,
            line_count=len(content.splitlines())
        )

        # 1. Markers
        result.markers = CommentMarkerParser.extract_markers(file_path, content)

        lines = content.splitlines()

        # 2. Extract Imports
        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("import ") or "require(" in stripped:
                match = self.IMPORT_PATTERN.search(line)
                if match:
                    raw_names = match.group(1)
                    module = match.group(2) or match.group(3) or ""
                    names = [n.strip() for n in raw_names.replace("{", "").replace("}", "").split(",")] if raw_names else []
                    result.imports.append(ImportStatement(
                        module=module,
                        imported_names=[n for n in names if n],
                        line_number=idx,
                        is_type_only="import type" in line
                    ))

        # 3. Extract Functions, Classes, Interfaces, Types
        for idx, line in enumerate(lines, start=1):
            is_export = "export " in line

            # Classes
            c_match = self.CLASS_PATTERN.search(line)
            if c_match:
                name = c_match.group(1)
                extends_cls = c_match.group(2)
                params = [f"extends {extends_cls}"] if extends_cls else []
                result.symbols.append(AstSymbol(
                    name=name,
                    kind="class",
                    file_path=file_path,
                    line_start=idx,
                    line_end=idx,
                    exported=is_export,
                    parameters=params
                ))
                continue

            # Interfaces
            i_match = self.INTERFACE_PATTERN.search(line)
            if i_match:
                name = i_match.group(1)
                result.symbols.append(AstSymbol(
                    name=name,
                    kind="interface",
                    file_path=file_path,
                    line_start=idx,
                    line_end=idx,
                    exported=is_export
                ))
                continue

            # Type Aliases
            t_match = self.TYPE_ALIAS_PATTERN.search(line)
            if t_match:
                name = t_match.group(1)
                result.symbols.append(AstSymbol(
                    name=name,
                    kind="type_alias",
                    file_path=file_path,
                    line_start=idx,
                    line_end=idx,
                    exported=is_export
                ))
                continue

            # Standard Functions
            f_match = self.EXPORT_FUNC_PATTERN.search(line)
            if f_match:
                name = f_match.group(1)
                params = [p.strip() for p in f_match.group(2).split(",") if p.strip()]
                ret_type = f_match.group(3).strip() if f_match.group(3) else None
                result.symbols.append(AstSymbol(
                    name=name,
                    kind="function",
                    file_path=file_path,
                    line_start=idx,
                    line_end=idx,
                    exported=is_export,
                    parameters=params,
                    return_type=ret_type
                ))
                continue

            # Arrow Functions
            a_match = self.EXPORT_ARROW_PATTERN.search(line)
            if a_match:
                name = a_match.group(1)
                params = [p.strip() for p in a_match.group(2).split(",") if p.strip()]
                ret_type = a_match.group(3).strip() if a_match.group(3) else None
                result.symbols.append(AstSymbol(
                    name=name,
                    kind="arrow_function",
                    file_path=file_path,
                    line_start=idx,
                    line_end=idx,
                    exported=is_export,
                    parameters=params,
                    return_type=ret_type
                ))

        return result
