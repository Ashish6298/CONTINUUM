"""
Project Continuum - Configuration & Environment Evidence Extractor
===================================================================
Milestone 2 - Phase 2: Configuration, Environment & Metadata Extraction.
Scans for project manifests (package.json, pyproject.toml, Cargo.toml, go.mod,
pubspec.yaml, Dockerfile, docker-compose.yml), detects lockfiles, extracts
dependencies, scripts, and build environments while redacting all secrets.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from core.enums import EvidenceType, EvidenceLevel
from core.evidence import Evidence
from core.state_models import (
    CanonicalProjectState,
    ManifestInfo,
    ProjectState,
)
from extractors.base import BaseEvidenceExtractor, DEFAULT_IGNORE_DIRS
from extractors.config.parsers import ManifestParser
from extractors.config.secret_sanitizer import SecretSanitizer


LOCKFILE_NAMES: Set[str] = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
    "Pipfile.lock",
    "pubspec.lock",
    "go.sum",
    "composer.lock"
}


class ConfigEvidenceExtractor(BaseEvidenceExtractor):
    """
    Extractor responsible for Phase 2: Manifest, config, and environment discovery.
    """

    @property
    def extractor_name(self) -> str:
        return "ConfigEvidenceExtractor"

    @property
    def supported_evidence_types(self) -> List[EvidenceType]:
        return [
            EvidenceType.CONFIG_FILE
        ]

    def can_extract(self, target_path_or_input: str) -> bool:
        path = Path(target_path_or_input)
        return path.exists() and path.is_dir()

    def extract(self, target_path_or_input: str, context: Optional[Dict[str, Any]] = None) -> List[Evidence]:
        root_path = Path(target_path_or_input).resolve()
        evidence_list: List[Evidence] = []

        manifests: List[ManifestInfo] = []
        lockfiles_detected: List[str] = []
        container_configs: List[Dict[str, Any]] = []
        env_templates: List[Dict[str, Any]] = []

        for path in sorted(root_path.rglob("*")):
            if not path.is_file():
                continue

            parts = set(path.relative_to(root_path).parts)
            if any(ignored in parts for ignored in DEFAULT_IGNORE_DIRS):
                continue

            filename = path.name
            rel_path = path.relative_to(root_path).as_posix()

            # 1. Lockfiles
            if filename in LOCKFILE_NAMES:
                lockfiles_detected.append(rel_path)
                continue

            # Read content safely
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            # 2. Manifests
            if filename == "package.json":
                m = ManifestParser.parse_package_json(rel_path, content)
                manifests.append(m)
            elif filename == "pyproject.toml":
                m = ManifestParser.parse_pyproject_toml(rel_path, content)
                manifests.append(m)
            elif filename == "Cargo.toml":
                m = ManifestParser.parse_cargo_toml(rel_path, content)
                manifests.append(m)
            elif filename == "go.mod":
                m = ManifestParser.parse_go_mod(rel_path, content)
                manifests.append(m)
            elif filename == "pubspec.yaml":
                m = ManifestParser.parse_pubspec_yaml(rel_path, content)
                manifests.append(m)
            elif filename == "Dockerfile" or filename.startswith("Dockerfile."):
                d = ManifestParser.parse_dockerfile(rel_path, content)
                container_configs.append(d)
            elif filename in {".env.example", ".env.template", ".env.sample"}:
                e = ManifestParser.parse_env_template(rel_path, content)
                env_templates.append(e)

        # 3. Create Manifest Evidence Records
        for m in manifests:
            ev = self.create_evidence(
                evidence_type=EvidenceType.CONFIG_FILE,
                summary=f"Discovered manifest {m.manifest_type} ({m.project_name or 'unnamed'} v{m.version or '0.0.0'}) with {len(m.dependencies)} dependencies",
                raw_payload={
                    "manifest_type": m.manifest_type,
                    "file_path": m.file_path,
                    "project_name": m.project_name,
                    "version": m.version,
                    "dependencies": m.dependencies,
                    "dev_dependencies": m.dev_dependencies,
                    "scripts": m.scripts
                },
                source_uri=m.file_path,
                locator=f"manifest:{m.file_path}"
            )
            m.evidence_id = ev.id
            evidence_list.append(ev)

        # 4. Create Project Environment & Container Evidence
        if container_configs or env_templates or lockfiles_detected:
            evidence_list.append(self.create_evidence(
                evidence_type=EvidenceType.CONFIG_FILE,
                summary=f"Discovered project configuration: {len(lockfiles_detected)} lockfiles, {len(container_configs)} containers, {len(env_templates)} env templates",
                raw_payload={
                    "lockfiles": lockfiles_detected,
                    "container_configs": container_configs,
                    "env_templates": env_templates
                },
                source_uri=str(root_path),
                locator="config:environment"
            ))

        return evidence_list

    def populate_project_state(self, root_dir: str, canonical_state: CanonicalProjectState) -> ProjectState:
        """Populates ProjectState.manifests and registers config evidence."""
        root_path = Path(root_dir).resolve()
        evidence_list = self.extract(str(root_path))

        manifest_records: List[ManifestInfo] = []

        for ev in evidence_list:
            canonical_state.add_evidence(ev)
            if "manifest_type" in ev.raw_payload:
                m = ManifestInfo(
                    manifest_type=ev.raw_payload["manifest_type"],
                    file_path=ev.raw_payload["file_path"],
                    project_name=ev.raw_payload.get("project_name"),
                    version=ev.raw_payload.get("version"),
                    dependencies=ev.raw_payload.get("dependencies", {}),
                    dev_dependencies=ev.raw_payload.get("dev_dependencies", {}),
                    scripts=ev.raw_payload.get("scripts", {}),
                    evidence_id=ev.id
                )
                manifest_records.append(m)

        ps = canonical_state.project_state
        ps.manifests.extend(manifest_records)
        ps.evidence_ids.extend([ev.id for ev in evidence_list])
        return ps
