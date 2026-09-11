"""
Project Continuum - Universal Comment Marker Parser
===================================================
Scans source files across various languages for TODO, FIXME, BUG, HACK markers.
"""

import re
from typing import List
from extractors.parsers.base import CommentMarker


class CommentMarkerParser:
    """
    Detects inline TODO, FIXME, BUG, HACK, and OPTIMIZE markers
    across different programming language comment formats (//, #, /*, --, etc.).
    """
    
    # Matches patterns like:
    # // TODO: fix this
    # # FIXME(user): handle null
    # /* BUG: memory leak */
    # -- TODO: sql migration
    MARKER_PATTERN = re.compile(
        r'(?:(?://|#|--|/\*|;)\s*)\b(TODO|FIXME|BUG|HACK|OPTIMIZE|NOTE|XXX)\b(?:\s*\((.*?)\))?\s*[:-]?\s*(.*?)(?:\*/)?$',
        re.IGNORECASE
    )

    @classmethod
    def extract_markers(cls, file_path: str, content: str) -> List[CommentMarker]:
        markers: List[CommentMarker] = []
        lines = content.splitlines()

        for idx, line in enumerate(lines, start=1):
            match = cls.MARKER_PATTERN.search(line)
            if match:
                marker_type = match.group(1).upper()
                author_scope = match.group(2)
                desc = match.group(3).strip()
                
                full_text = f"({author_scope}) {desc}" if author_scope else desc
                if not full_text:
                    full_text = line.strip()

                markers.append(CommentMarker(
                    marker_type=marker_type,
                    text=full_text,
                    line_number=idx,
                    file_path=file_path
                ))

        return markers
