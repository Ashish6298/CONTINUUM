"""
Project Continuum - Python Source Code & AST Parser
===================================================
Robust AST parser for Python source files extracting modules, classes,
methods, async/sync functions, parameter signatures, docstrings, imports,
and exported symbols. Safely captures syntax errors without crashing.
"""

import ast
import textwrap
from typing import List, Optional

from core.state_models import AstSymbol
from extractors.parsers.base import (
    ILanguageParser,
    ImportStatement,
    ParseError,
    ParserResult
)
from extractors.parsers.comment_parser import CommentMarkerParser


class PythonParser(ILanguageParser):
    """
    AST-based Python source code analyzer.
    """

    @property
    def language_name(self) -> str:
        return "Python"

    @property
    def supported_extensions(self) -> List[str]:
        return [".py", ".pyw", ".pyi"]

    def parse_source(self, file_path: str, content: str) -> ParserResult:
        result = ParserResult(
            file_path=file_path,
            language=self.language_name,
            line_count=len(content.splitlines())
        )

        # 1. Extract TODO/FIXME markers
        result.markers = CommentMarkerParser.extract_markers(file_path, content)

        # 2. Parse AST safely
        try:
            tree = ast.parse(textwrap.dedent(content), filename=file_path)
        except SyntaxError as e:
            result.errors.append(ParseError(
                file_path=file_path,
                message=f"SyntaxError: {e.msg}",
                line_number=e.lineno
            ))
            return result
        except Exception as e:
            result.errors.append(ParseError(
                file_path=file_path,
                message=f"ParseError: {str(e)}",
                line_number=None
            ))
            return result

        # 3. Extract module level __all__ if present
        all_exports: List[str] = []
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    all_exports.append(elt.value)
        result.exported_symbols = all_exports

        # 4. Extract symbols and imports
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    result.imports.append(ImportStatement(
                        module=alias.name,
                        alias=alias.asname,
                        line_number=node.lineno
                    ))
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                names = [alias.name for alias in node.names]
                result.imports.append(ImportStatement(
                    module=mod,
                    imported_names=names,
                    line_number=node.lineno
                ))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbol = self._parse_function(node, file_path, is_method=False, parent_class=None, all_exports=all_exports)
                result.symbols.append(symbol)
            elif isinstance(node, ast.ClassDef):
                class_symbol, methods = self._parse_class(node, file_path, all_exports=all_exports)
                result.symbols.append(class_symbol)
                result.symbols.extend(methods)

        return result

    def _parse_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        file_path: str,
        is_method: bool,
        parent_class: Optional[str],
        all_exports: List[str]
    ) -> AstSymbol:
        # Parameters
        params: List[str] = []
        for arg in node.args.args:
            arg_str = arg.arg
            if arg.annotation:
                arg_str += f": {ast.unparse(arg.annotation)}"
            params.append(arg_str)

        # Return annotation
        return_type = ast.unparse(node.returns) if node.returns else None

        # Docstring
        docstring = ast.get_docstring(node)

        # Determine export status
        is_exported = False
        if all_exports:
            is_exported = node.name in all_exports
        else:
            # Default python rule: exported if not starting with '_'
            is_exported = not node.name.startswith("_")

        kind = "method" if is_method else ("async_function" if isinstance(node, ast.AsyncFunctionDef) else "function")
        qualified_name = f"{parent_class}.{node.name}" if parent_class else node.name

        return AstSymbol(
            name=qualified_name,
            kind=kind,
            file_path=file_path,
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
            exported=is_exported,
            docstring=docstring,
            parameters=params,
            return_type=return_type
        )

    def _parse_class(
        self,
        node: ast.ClassDef,
        file_path: str,
        all_exports: List[str]
    ) -> tuple[AstSymbol, List[AstSymbol]]:
        docstring = ast.get_docstring(node)
        bases = [ast.unparse(b) for b in node.bases]
        
        is_exported = False
        if all_exports:
            is_exported = node.name in all_exports
        else:
            is_exported = not node.name.startswith("_")

        class_symbol = AstSymbol(
            name=node.name,
            kind="class",
            file_path=file_path,
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
            exported=is_exported,
            docstring=docstring,
            parameters=bases  # Record base classes in parameters
        )

        methods: List[AstSymbol] = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_sym = self._parse_function(item, file_path, is_method=True, parent_class=node.name, all_exports=all_exports)
                methods.append(method_sym)

        return class_symbol, methods
