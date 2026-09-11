"""
Project Continuum - Extractors Subsystem Package Initialization
"""

from extractors.base import BaseEvidenceExtractor, DEFAULT_IGNORE_DIRS, CONFIG_FILE_NAMES, DOC_EXTENSIONS
from extractors.workspace_extractor import WorkspaceEvidenceExtractor
from extractors.config_extractor import ConfigEvidenceExtractor, LOCKFILE_NAMES
from extractors.git_extractor import GitEvidenceExtractor
from extractors.verification_extractor import VerificationEvidenceExtractor
from extractors.conversation_extractor import ConversationEvidenceExtractor
from extractors.conversation.models import ConversationTranscript, ConversationTurn, TurnRole
from extractors.conversation.analyzers import TranscriptAnalyzer, TranscriptAnalysisResult
from extractors.verification.runners import VerificationRunner, TestOutputParser, ExecutionResult, ParsedTestSummary
from extractors.config.secret_sanitizer import SecretSanitizer
from extractors.config.parsers import ManifestParser
from extractors.parsers.base import ILanguageParser, ParserResult, CommentMarker, ImportStatement, ParseError
from extractors.parsers.comment_parser import CommentMarkerParser
from extractors.parsers.python_parser import PythonParser
from extractors.parsers.js_ts_parser import JavaScriptTypeScriptParser

__all__ = [
    "BaseEvidenceExtractor",
    "WorkspaceEvidenceExtractor",
    "ConfigEvidenceExtractor",
    "GitEvidenceExtractor",
    "VerificationEvidenceExtractor",
    "ConversationEvidenceExtractor",
    "ConversationTranscript",
    "ConversationTurn",
    "TurnRole",
    "TranscriptAnalyzer",
    "TranscriptAnalysisResult",
    "VerificationRunner",
    "TestOutputParser",
    "ExecutionResult",
    "ParsedTestSummary",
    "SecretSanitizer",
    "ManifestParser",
    "DEFAULT_IGNORE_DIRS",
    "CONFIG_FILE_NAMES",
    "DOC_EXTENSIONS",
    "LOCKFILE_NAMES",
    "ILanguageParser",
    "ParserResult",
    "CommentMarker",
    "ImportStatement",
    "ParseError",
    "CommentMarkerParser",
    "PythonParser",
    "JavaScriptTypeScriptParser",
]
