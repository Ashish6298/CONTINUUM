"""
Project Continuum - Extractors Subsystem Package Initialization
"""

from extractors.base import BaseEvidenceExtractor
from extractors.workspace_extractor import WorkspaceEvidenceExtractor
from extractors.parsers.base import ILanguageParser, ParserResult, CommentMarker, ImportStatement, ParseError
from extractors.parsers.comment_parser import CommentMarkerParser
from extractors.parsers.python_parser import PythonParser
from extractors.parsers.js_ts_parser import JavaScriptTypeScriptParser

__all__ = [
    "BaseEvidenceExtractor",
    "WorkspaceEvidenceExtractor",
    "ILanguageParser",
    "ParserResult",
    "CommentMarker",
    "ImportStatement",
    "ParseError",
    "CommentMarkerParser",
    "PythonParser",
    "JavaScriptTypeScriptParser",
]
