"""
Project Continuum - Parser Base and Common Types
=================================================
Defines the ILanguageParser contract and ParserResult structure.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from core.state_models import AstSymbol


@dataclass
class CommentMarker:
    """Represents a TODO, FIXME, BUG, HACK, or NOTE found in source code."""
    marker_type: str  # TODO, FIXME, BUG, HACK, NOTE
    text: str
    line_number: int
    file_path: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "marker_type": self.marker_type,
            "text": self.text,
            "line_number": self.line_number,
            "file_path": self.file_path
        }


@dataclass
class ImportStatement:
    """Represents an imported module, package, or symbol."""
    module: str
    imported_names: List[str] = field(default_factory=list)
    alias: Optional[str] = None
    line_number: int = 1
    is_type_only: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module": self.module,
            "imported_names": self.imported_names,
            "alias": self.alias,
            "line_number": self.line_number,
            "is_type_only": self.is_type_only
        }


@dataclass
class ParseError:
    """Non-fatal parse error recorded when analyzing malformed files."""
    file_path: str
    message: str
    line_number: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "message": self.message,
            "line_number": self.line_number
        }


@dataclass
class ParserResult:
    """Structured result returned by a language parser."""
    file_path: str
    language: str
    symbols: List[AstSymbol] = field(default_factory=list)
    imports: List[ImportStatement] = field(default_factory=list)
    markers: List[CommentMarker] = field(default_factory=list)
    errors: List[ParseError] = field(default_factory=list)
    line_count: int = 0
    exported_symbols: List[str] = field(default_factory=list)


@runtime_checkable
class ILanguageParser(Protocol):
    """
    Contract implemented by all language-specific source parsers.
    """
    @property
    def language_name(self) -> str:
        ...

    @property
    def supported_extensions(self) -> List[str]:
        ...

    def parse_source(self, file_path: str, content: str) -> ParserResult:
        ...
