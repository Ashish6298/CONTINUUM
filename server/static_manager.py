"""
Project Continuum - Embedded Dashboard Static Asset Server
===========================================================
Milestone 27 - Phase 29: Embedded Dashboard Architecture & Asset Serving.
Resolves, reads, and serves embedded dashboard assets (HTML, CSS, JS, SVG, etc.)
from package resources or local filesystem with optimal MIME types and caching headers.
"""

from importlib import resources
import mimetypes
import os
from pathlib import Path
from typing import Dict, Optional, Tuple, Union


class StaticAssetManager:
    """
    Manages resolution and delivery of embedded web dashboard assets.
    Works seamlessly in both editable source installations and built wheels.
    """

    MIME_TYPES: Dict[str, str] = {
        ".html": "text/html; charset=utf-8",
        ".htm": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".mjs": "application/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".ico": "image/x-icon",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
        ".map": "application/json; charset=utf-8",
    }

    def __init__(self, static_dir_override: Optional[Path] = None):
        if static_dir_override:
            self._static_dir = Path(static_dir_override).resolve()
        else:
            self._static_dir = Path(__file__).parent / "static"

    @property
    def static_dir(self) -> Path:
        """Returns the resolved static directory path."""
        return self._static_dir

    def get_mime_type(self, path: Union[str, Path]) -> str:
        """Determines the appropriate Content-Type for a file."""
        ext = Path(path).suffix.lower()
        if ext in self.MIME_TYPES:
            return self.MIME_TYPES[ext]
        mime, _ = mimetypes.guess_type(str(path))
        return mime or "application/octet-stream"

    def resolve_asset(self, request_path: str) -> Optional[Tuple[bytes, str]]:
        """
        Resolves a requested HTTP URL path to an embedded static asset.
        Returns a tuple of (content_bytes, content_type) or None if not found.
        Prevents directory traversal outside the static root.
        """
        clean_path = request_path.split("?")[0].split("#")[0].strip()

        # Map root URL or /dashboard to index.html
        if clean_path in ("", "/", "/dashboard", "/dashboard/"):
            clean_path = "index.html"
        else:
            clean_path = clean_path.lstrip("/")

        # Check in local filesystem (source tree or wheel unpacked directory)
        candidate = (self._static_dir / clean_path).resolve()

        # Ensure security against directory traversal
        try:
            candidate.relative_to(self._static_dir.resolve())
        except (ValueError, RuntimeError):
            return None

        if candidate.is_file():
            try:
                content = candidate.read_bytes()
                mime_type = self.get_mime_type(candidate)
                return content, mime_type
            except OSError:
                return None

        # Fallback to importlib.resources for zipped eggs/wheels if needed
        try:
            package_name = "server.static"
            # If standard relative path inside package
            sub_resource = clean_path.replace("\\", "/")
            if "/" not in sub_resource:
                if hasattr(resources, "files"):
                    traversable = resources.files(package_name).joinpath(sub_resource)
                    if traversable.is_file():
                        content = traversable.read_bytes()
                        mime_type = self.get_mime_type(sub_resource)
                        return content, mime_type
        except Exception:
            pass

        return None
