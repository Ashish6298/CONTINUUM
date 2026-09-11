"""
Project Continuum - Contradiction Subsystem Package
===================================================
Milestone 3 - Phase 7.
"""

from contradictions.models import (
    ContradictionSeverity,
    ContradictionType,
    DiscrepancyLedger,
)
from contradictions.detector import ContradictionDetector

__all__ = [
    "ContradictionSeverity",
    "ContradictionType",
    "DiscrepancyLedger",
    "ContradictionDetector",
]
