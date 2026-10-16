"""
Project Continuum — Artifact Reference and Snapshot Management Engine
=====================================================================
Milestone 41 - Phase 70: Artifact References and Snapshots.

Implements core domain rules and safety guards for checkpoint artifacts:
1. References by default; optional user-selected snapshot copies where safe.
2. Explicit labeling: Live Reference vs Snapshot, capture timestamp, and storage visibility.
3. Resilient handling of missing resources (graceful degradation, no crashes).
4. Strict privacy guards: High-risk credential files (.env, id_rsa, *.pem, etc.)
   are never snapshot-copied; inline secrets are redacted.
5. Strict size bounding: Never copy entire folders or large files silently.
   Per-file limit (512 KB) and total checkpoint budget (2 MB) enforced.
6. Portability: Normalizes workspace paths to clean relative POSIX paths.
7. Zero external dependencies: Python standard library only.
"""

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from core.checkpoint import ArtifactReference
from core.enums import ArtifactMode
from server.sanitizer import DaemonSanitizer


class ArtifactError(Exception):
    """Base exception for artifact operations."""
    pass


class ArtifactSnapshotError(ArtifactError):
    """Raised when an artifact cannot be captured as a snapshot (e.g. folder, binary)."""
    pass


class ArtifactPrivacyError(ArtifactError):
    """Raised when an artifact cannot be snapshot-captured due to privacy/secret rules."""
    pass


class ArtifactSizeLimitError(ArtifactError):
    """Raised when an artifact exceeds maximum safe snapshot size limits."""
    pass


class ArtifactManager:
    """
    Manages artifact references and immutable snapshot capture.
    Guarantees:
    - References by default.
    - Snapshot only where safe and explicitly selected.
    - Directory copying strictly prohibited.
    - Size-bounded and secret-sanitized.
    """

    # Maximum file size allowed for an individual snapshot copy (512 KB)
    MAX_SNAPSHOT_FILE_BYTES: int = 512 * 1024

    # Maximum total snapshot content budget allowed per checkpoint (2 MB)
    MAX_TOTAL_SNAPSHOT_BYTES: int = 2 * 1024 * 1024

    # Safe text extensions permitted for text snapshot copies
    SAFE_TEXT_EXTENSIONS: Set[str] = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
        ".json", ".jsonl", ".md", ".markdown", ".txt", ".rst",
        ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
        ".html", ".htm", ".css", ".scss", ".sass", ".less",
        ".sh", ".bash", ".zsh", ".bat", ".cmd", ".ps1",
        ".sql", ".graphql", ".gql", ".xml", ".svg", ".csv",
        ".tsv", ".diff", ".patch", ".proto", ".env.example",
    }

    @classmethod
    def normalize_path(cls, path_or_uri: str, workspace_root: Optional[Path] = None) -> str:
        """
        Normalizes a path or URI into a clean, portable format.
        Converts absolute paths within workspace_root to relative POSIX paths.
        Preserves URI schemes (http://, https://, file://, etc.).
        """
        if not path_or_uri or not isinstance(path_or_uri, str):
            return ""

        clean = path_or_uri.strip()
        # Keep external URIs intact
        if "://" in clean:
            return clean

        p = Path(clean)
        if workspace_root:
            ws_resolved = Path(workspace_root).resolve()
            try:
                # If path is inside workspace, make it relative
                if p.is_absolute():
                    p_resolved = p.resolve()
                    rel = p_resolved.relative_to(ws_resolved)
                    return rel.as_posix()
            except (ValueError, RuntimeError):
                pass

        # Standardize forward slashes for relative paths
        return clean.replace("\\", "/").lstrip("/")

    @classmethod
    def resolve_local_path(cls, path_or_uri: str, workspace_root: Optional[Path] = None) -> Optional[Path]:
        """
        Resolves a portable path_or_uri to a local filesystem Path.
        Returns None if external URI.
        """
        if not path_or_uri:
            return None

        clean = path_or_uri.strip()
        if "://" in clean:
            if clean.startswith("file:///"):
                clean = clean[8:]
            elif clean.startswith("file://"):
                clean = clean[7:]
            else:
                return None  # Remote or non-file URI

        p = Path(clean)
        if p.is_absolute():
            return p.resolve()

        if workspace_root:
            return (Path(workspace_root) / clean).resolve()

        return p.resolve()

    @classmethod
    def is_safe_text_file(cls, path_or_name: str) -> bool:
        """Determines whether a file extension is text-based and safe for snapshot copying."""
        p = Path(path_or_name)
        ext = p.suffix.lower()
        if ext in cls.SAFE_TEXT_EXTENSIONS:
            return True
        # Common text dotfiles (e.g. .gitignore, .dockerignore)
        if p.name.lower() in {".gitignore", ".dockerignore", ".editorconfig", "license", "dockerfile", "makefile"}:
            return True
        return False

    @classmethod
    def inspect_resource(cls, path_or_uri: str, workspace_root: Optional[Path] = None) -> Dict[str, Any]:
        """
        Inspects a target resource without mutating or reading full content.
        Returns existence, directory status, size, privacy risk, and snapshot safety.
        """
        norm_path = cls.normalize_path(path_or_uri, workspace_root)
        local_p = cls.resolve_local_path(norm_path, workspace_root)

        is_uri = "://" in path_or_uri and not path_or_uri.startswith("file://")
        if is_uri:
            return {
                "path_or_uri": path_or_uri,
                "name": Path(path_or_uri.split("?")[0]).name or path_or_uri,
                "exists": True,
                "is_directory": False,
                "size_bytes": None,
                "checksum_sha256": None,
                "storage_visibility": "external_uri",
                "is_safe_for_snapshot": False,
                "is_high_risk": False,
                "reason": "External URIs are supported as references only.",
            }

        if not local_p or not local_p.exists():
            return {
                "path_or_uri": norm_path,
                "name": Path(norm_path).name or norm_path,
                "exists": False,
                "is_directory": False,
                "size_bytes": 0,
                "checksum_sha256": None,
                "storage_visibility": "missing",
                "is_safe_for_snapshot": False,
                "is_high_risk": False,
                "reason": "Resource not found on filesystem.",
            }

        # Check if directory
        is_dir = local_p.is_dir()
        if is_dir:
            return {
                "path_or_uri": norm_path,
                "name": local_p.name,
                "exists": True,
                "is_directory": True,
                "size_bytes": 0,
                "checksum_sha256": None,
                "storage_visibility": "workspace_local",
                "is_safe_for_snapshot": False,
                "is_high_risk": False,
                "reason": "Directories cannot be captured as snapshots; select individual files or link as reference.",
            }

        # Check high-risk privacy
        is_high_risk = DaemonSanitizer.is_high_risk_file(local_p)
        if is_high_risk:
            return {
                "path_or_uri": norm_path,
                "name": local_p.name,
                "exists": True,
                "is_directory": False,
                "size_bytes": local_p.stat().st_size,
                "checksum_sha256": None,
                "storage_visibility": "workspace_local",
                "is_safe_for_snapshot": False,
                "is_high_risk": True,
                "reason": "High-risk credential/secret file excluded from snapshot capture for privacy (I-10).",
            }

        size = local_p.stat().st_size
        if size > cls.MAX_SNAPSHOT_FILE_BYTES:
            return {
                "path_or_uri": norm_path,
                "name": local_p.name,
                "exists": True,
                "is_directory": False,
                "size_bytes": size,
                "checksum_sha256": None,
                "storage_visibility": "workspace_local",
                "is_safe_for_snapshot": False,
                "is_high_risk": False,
                "reason": f"File size ({size} bytes) exceeds snapshot limit ({cls.MAX_SNAPSHOT_FILE_BYTES} bytes). Link as reference instead.",
            }

        # Compute quick SHA-256
        sha256 = cls.compute_file_sha256(local_p)
        is_text = cls.is_safe_text_file(local_p.name)

        return {
            "path_or_uri": norm_path,
            "name": local_p.name,
            "exists": True,
            "is_directory": False,
            "size_bytes": size,
            "checksum_sha256": sha256,
            "storage_visibility": "workspace_local",
            "is_safe_for_snapshot": is_text,
            "is_high_risk": False,
            "reason": None if is_text else "Binary file format not supported for snapshot copy. Link as reference instead.",
        }

    @classmethod
    def compute_file_sha256(cls, file_path: Path) -> Optional[str]:
        """Calculates SHA256 hex digest of a local file."""
        try:
            hasher = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return None

    @classmethod
    def create_reference(
        cls,
        path_or_uri: str,
        name_or_workspace: Optional[Union[str, Path]] = None,
        workspace_root: Optional[Path] = None
    ) -> ArtifactReference:
        """
        Creates a LIVE REFERENCE artifact (default behavior).
        Never copies content; stores path, status, and metadata.
        Supports:
          create_reference("path", workspace_root=ws)
          create_reference("path", "custom_name", ws)
          create_reference("path", ws)  # convenience
        """
        if isinstance(name_or_workspace, (Path, os.PathLike)) or (isinstance(name_or_workspace, str) and workspace_root is None and ("\\" in name_or_workspace or "/" in name_or_workspace or name_or_workspace.startswith("."))):
            # Positional workspace_root provided
            actual_ws = Path(name_or_workspace)
            actual_name = None
        else:
            actual_ws = workspace_root
            actual_name = str(name_or_workspace) if name_or_workspace is not None else None

        inspection = cls.inspect_resource(path_or_uri, actual_ws)
        art_name = actual_name or inspection["name"]
        norm_path = inspection["path_or_uri"]

        return ArtifactReference(
            name=art_name,
            path_or_uri=norm_path,
            mode=ArtifactMode.REFERENCE,
            captured_at=datetime.now(timezone.utc).isoformat(),
            checksum_sha256=inspection.get("checksum_sha256"),
            size_bytes=inspection.get("size_bytes"),
            snapshot_content=None,
            storage_visibility=inspection["storage_visibility"],
            is_present=inspection["exists"],
            metadata={
                "is_directory": inspection["is_directory"],
                "reason": inspection.get("reason"),
            }
        )

    @classmethod
    def create_snapshot(
        cls,
        path_or_uri: str,
        name_or_workspace: Optional[Union[str, Path]] = None,
        workspace_root: Optional[Path] = None,
        custom_content: Optional[str] = None,
        max_bytes: int = MAX_SNAPSHOT_FILE_BYTES
    ) -> ArtifactReference:
        """
        Creates an IMMUTABLE SNAPSHOT artifact copy with explicit user consent.
        Strictly guards against directories, credentials, binary files, and size bounds.
        Supports:
          create_snapshot("path", workspace_root=ws)
          create_snapshot("path", "custom_name", ws)
          create_snapshot("path", ws)  # convenience
        """
        if isinstance(name_or_workspace, (Path, os.PathLike)) or (isinstance(name_or_workspace, str) and workspace_root is None and ("\\" in name_or_workspace or "/" in name_or_workspace or name_or_workspace.startswith("."))):
            actual_ws = Path(name_or_workspace)
            actual_name = None
        else:
            actual_ws = workspace_root
            actual_name = str(name_or_workspace) if name_or_workspace is not None else None

        inspection = cls.inspect_resource(path_or_uri, actual_ws)
        art_name = actual_name or inspection["name"]
        norm_path = inspection["path_or_uri"]

        if inspection.get("is_directory"):
            raise ArtifactSnapshotError(
                f"Cannot capture directory '{path_or_uri}' as snapshot. "
                "Folders must never be copied silently; link as reference or select individual files."
            )

        if inspection.get("is_high_risk"):
            raise ArtifactPrivacyError(
                f"Cannot snapshot '{path_or_uri}': High-risk credential/secret file excluded for privacy (I-10)."
            )

        # Read content from file if custom_content is not provided
        if custom_content is not None:
            raw_content = str(custom_content)
        else:
            if not inspection["exists"]:
                raise ArtifactSnapshotError(f"Cannot capture snapshot: Resource '{path_or_uri}' not found on filesystem.")

            size = inspection.get("size_bytes", 0) or 0
            if size > max_bytes:
                raise ArtifactSizeLimitError(
                    f"File '{path_or_uri}' ({size} bytes) exceeds maximum snapshot size limit ({max_bytes} bytes)."
                )

            local_p = cls.resolve_local_path(norm_path, actual_ws)
            try:
                raw_content = local_p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                raise ArtifactSnapshotError(
                    f"File '{path_or_uri}' contains binary data. Snapshots are supported for text files only."
                )
            except Exception as e:
                raise ArtifactSnapshotError(f"Failed to read file '{path_or_uri}' for snapshot: {e}")

        # Check text length / byte bound
        content_bytes = raw_content.encode("utf-8")
        if len(content_bytes) > max_bytes:
            raise ArtifactSizeLimitError(
                f"Snapshot content length ({len(content_bytes)} bytes) exceeds maximum size limit ({max_bytes} bytes)."
            )

        # Sanitize inline secrets
        sanitized_content = DaemonSanitizer.sanitize_text(raw_content)
        sha256 = hashlib.sha256(sanitized_content.encode("utf-8")).hexdigest()

        return ArtifactReference(
            name=art_name,
            path_or_uri=norm_path,
            mode=ArtifactMode.SNAPSHOT,
            captured_at=datetime.now(timezone.utc).isoformat(),
            checksum_sha256=sha256,
            size_bytes=len(sanitized_content.encode("utf-8")),
            snapshot_content=sanitized_content,
            storage_visibility="embedded_snapshot",
            is_present=True,
            metadata={
                "original_size_bytes": len(content_bytes),
                "is_sanitized": True,
            }
        )

    @classmethod
    def resolve_artifact_status(
        cls,
        artifact: ArtifactReference,
        workspace_root: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Evaluates the current state of an existing artifact relative to the live workspace.
        Handles missing resources gracefully and reports live vs snapshot divergences.
        """
        is_snap = artifact.is_snapshot
        local_p = cls.resolve_local_path(artifact.path_or_uri, workspace_root)
        local_exists = bool(local_p and local_p.exists())

        result: Dict[str, Any] = {
            "name": artifact.name,
            "path_or_uri": artifact.path_or_uri,
            "mode": artifact.mode.value if isinstance(artifact.mode, ArtifactMode) else str(artifact.mode),
            "captured_at": artifact.captured_at,
            "is_snapshot": is_snap,
            "storage_visibility": artifact.storage_visibility,
            "live_file_exists": local_exists,
        }

        if is_snap:
            # Snapshots remain valid even if live file is deleted from workspace!
            result["is_valid"] = bool(artifact.snapshot_content is not None)
            result["has_content"] = bool(artifact.snapshot_content)
            result["content_length"] = len(artifact.snapshot_content or "")
            if not local_exists:
                result["live_status"] = "deleted_from_workspace"
                result["live_message"] = "Live workspace file no longer exists. Snapshot copy preserved in checkpoint."
            else:
                current_sha = cls.compute_file_sha256(local_p)
                if current_sha and artifact.checksum_sha256 and current_sha != artifact.checksum_sha256:
                    result["live_status"] = "diverged"
                    result["live_message"] = "Live workspace file has changed since snapshot was captured."
                else:
                    result["live_status"] = "identical"
                    result["live_message"] = "Live workspace file matches captured snapshot."
        else:
            # References point to live workspace file
            if not local_exists:
                result["is_valid"] = False
                result["storage_visibility"] = "missing"
                result["live_status"] = "missing"
                result["live_message"] = "Referenced file not found on filesystem."
            else:
                result["is_valid"] = True
                result["storage_visibility"] = "workspace_local"
                result["live_status"] = "present"
                result["live_message"] = "Live workspace file present and accessible."

        return result

    @classmethod
    def validate_and_process_artifacts(
        cls,
        raw_artifacts: List[Any],
        workspace_root: Optional[Path] = None,
        exclude_high_risk: bool = True
    ) -> List[ArtifactReference]:
        """
        Validates, normalizes, and packages a list of artifact inputs for a checkpoint.
        Ensures references by default, prevents directory snapshotting, and respects size bounds.
        """
        processed: List[ArtifactReference] = []
        total_snapshot_bytes = 0

        for item in raw_artifacts:
            if not item:
                continue

            if isinstance(item, ArtifactReference):
                art = item
            elif isinstance(item, dict):
                art = ArtifactReference.from_dict(item)
            elif isinstance(item, str):
                art = ArtifactReference(name=Path(item).name, path_or_uri=item)
            else:
                continue

            # Check privacy exclusions
            if exclude_high_risk and DaemonSanitizer.is_high_risk_file(art.path_or_uri):
                continue

            # Normalize path
            norm_path = cls.normalize_path(art.path_or_uri, workspace_root)
            art.path_or_uri = norm_path

            # Determine mode
            if art.is_snapshot:
                # If requested as snapshot, validate snapshot constraints
                inspection = cls.inspect_resource(norm_path, workspace_root)
                if inspection.get("is_directory"):
                    # Silently downgrade or reject directory snapshot to live reference
                    art.mode = ArtifactMode.REFERENCE
                    art.snapshot_content = None
                    art.storage_visibility = "workspace_local"
                    art.metadata["warning"] = "Directories cannot be snapshot-captured; converted to reference."
                elif inspection.get("is_high_risk"):
                    # Cannot snapshot high-risk files
                    continue
                else:
                    # Enforce per-file and total budget
                    content = art.snapshot_content
                    if content is None and inspection["exists"]:
                        local_p = cls.resolve_local_path(norm_path, workspace_root)
                        try:
                            content = local_p.read_text(encoding="utf-8")
                        except Exception:
                            content = None

                    if content is not None:
                        sanitized = DaemonSanitizer.sanitize_text(content)
                        s_bytes = len(sanitized.encode("utf-8"))

                        if s_bytes <= cls.MAX_SNAPSHOT_FILE_BYTES and (total_snapshot_bytes + s_bytes) <= cls.MAX_TOTAL_SNAPSHOT_BYTES:
                            art.snapshot_content = sanitized
                            art.size_bytes = s_bytes
                            art.checksum_sha256 = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()
                            art.storage_visibility = "embedded_snapshot"
                            art.is_present = True
                            total_snapshot_bytes += s_bytes
                        else:
                            # Size limit reached - downgrade to reference
                            art.mode = ArtifactMode.REFERENCE
                            art.snapshot_content = None
                            art.storage_visibility = "workspace_local"
                            art.metadata["warning"] = "Snapshot size limit exceeded; converted to live reference."
                    else:
                        art.mode = ArtifactMode.REFERENCE
                        art.storage_visibility = inspection["storage_visibility"]
                        art.is_present = inspection["exists"]
            else:
                # Default mode: REFERENCE
                art.mode = ArtifactMode.REFERENCE
                art.snapshot_content = None
                inspection = cls.inspect_resource(norm_path, workspace_root)
                art.storage_visibility = inspection["storage_visibility"]
                art.is_present = inspection["exists"]
                if inspection["exists"]:
                    art.size_bytes = inspection.get("size_bytes")
                    art.checksum_sha256 = inspection.get("checksum_sha256")

            processed.append(art)

        return processed
