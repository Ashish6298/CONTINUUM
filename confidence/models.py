"""
Project Continuum - Confidence Metrics & Breakdown Models
=========================================================
Milestone 3 - Phase 8: Confidence Calculation & Status Evaluation.
Defines structured multi-dimensional confidence breakdown schemas.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class ConfidenceBreakdown:
    """
    Explainable multi-dimensional confidence scoring breakdown.
    Total potential raw score: 100.0%.
    """
    target_id: str
    implementation_presence: float = 0.0  # Max 35.0 (AST symbols, files, exports)
    test_existence: float = 0.0           # Max 15.0 (Test files / suites present)
    test_execution_pass: float = 0.0      # Max 30.0 (Passing test exit codes)
    git_consistency: float = 0.0          # Max 10.0 (Clean working tree & commits)
    documentation_presence: float = 0.0   # Max 10.0 (Docstrings / Markdown)
    
    # Penalties & Contradiction Caps:
    raw_score: float = 0.0
    contradiction_penalties: float = 0.0
    contradiction_cap: Optional[float] = None
    final_score: float = 0.0              # Clamped 0.0 - 100.0%
    
    explanation: str = ""
    contributing_evidence_ids: List[str] = field(default_factory=list)
    active_contradiction_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConfidenceBreakdown":
        return cls(**data)
