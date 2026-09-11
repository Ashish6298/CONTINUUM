"""
Project Continuum - Base Evidence Extractor & Classification
============================================================
Defines the BaseEvidenceExtractor and workspace classification logic.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from core.enums import EvidenceType, EvidenceLevel
from core.evidence import Evidence, EvidenceProvenance
from core.interfaces import IEvidenceExtractor


# Standard directories to ignore during workspace scanning
DEFAULT_IGNORE_DIRS: Set[str] = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "env",
    ".idea",
    ".vscode",
    "dist",
    "build",
    ".egg-info",
    "target",
    ".dart_tool",
    "coverage",
    ".continuum"
}

# Standard configuration filenames
CONFIG_FILE_NAMES: Set[str] = {
    "package.json",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "pubspec.yaml",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Makefile",
    "CMakeLists.txt",
    "tsconfig.json"
}

# Documentation extensions
DOC_EXTENSIONS: Set[str] = {
    ".md",
    ".markdown",
    ".rst",
    ".txt",
    ".adoc"
}


class BaseEvidenceExtractor(ABC):
    """
    Abstract base class providing standard helper methods for all evidence extractors.
    """

    @property
    @abstractmethod
    def extractor_name(self) -> str:
        """Unique identifier for this extractor."""
        pass

    @property
    @abstractmethod
    def supported_evidence_types(self) -> List[EvidenceType]:
        """Evidence types this extractor produces."""
        pass

    @abstractmethod
    def can_extract(self, target_path_or_input: str) -> bool:
        """Determines if this extractor is applicable to the target."""
        pass

    @abstractmethod
    def extract(self, target_path_or_input: str, context: Optional[Dict[str, Any]] = None) -> List[Evidence]:
        """Harvests verifiable evidence from the target."""
        pass

    def create_evidence(
        self,
        evidence_type: EvidenceType,
        summary: str,
        raw_payload: Dict[str, Any],
        source_uri: str,
        locator: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Evidence:
        """Helper to create standardized, verified Evidence records with provenance."""
        level = EvidenceLevel.get_level_for_type(evidence_type)
        prov = EvidenceProvenance(
            extractor_name=self.extractor_name,
            source_uri=source_uri,
            locator=locator
        )
        return Evidence(
            type=evidence_type,
            level=level,
            summary=summary,
            raw_payload=raw_payload,
            provenance=prov,
            metadata=metadata or {}
        )
