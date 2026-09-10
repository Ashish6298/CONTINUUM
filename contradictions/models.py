"""
Project Continuum - Contradiction & Discrepancy Models
======================================================
Milestone 3 - Phase 7: Contradiction Detection Engine.
Defines contradiction categories, discrepancy severities, and the discrepancy ledger.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from core.state_models import ContradictionRecord


class ContradictionType(str, Enum):
    """Categories of discrepancies identified across Continuum's state boundaries."""
    CLAIM_VS_MISSING_IMPLEMENTATION = "claim_vs_missing_implementation"
    CLAIM_VS_FAILING_TEST = "claim_vs_failing_test"
    DOC_VS_MISSING_SYMBOL = "doc_vs_missing_symbol"
    INCOMPLETE_DEPENDENCY = "incomplete_dependency"
    STALE_PROJECT_INFO = "stale_project_info"
    UNVERIFIED_CLAIM = "unverified_claim"


class ContradictionSeverity(str, Enum):
    """Severity levels for detected contradictions."""
    HIGH = "HIGH"        # Direct falsehood (e.g. claiming tests pass when they fail)
    MEDIUM = "MEDIUM"    # Significant drift (e.g. docs reference non-existent symbols)
    LOW = "LOW"          # Minor divergence (e.g. uncommitted changes after claiming done)


@dataclass
class DiscrepancyLedger:
    """
    Maintains an audit ledger of all unresolved and resolved discrepancies.
    Ensures complete transparency for developers and subsequent AI agents.
    """
    records: List[ContradictionRecord] = field(default_factory=list)

    def add_record(self, record: ContradictionRecord) -> None:
        """Appends a new contradiction record if not already present."""
        if not any(r.id == record.id for r in self.records):
            self.records.append(record)

    def get_unresolved(self) -> List[ContradictionRecord]:
        """Returns all currently unresolved contradictions."""
        return [r for r in self.records if not r.resolved]

    def get_by_severity(self, severity: str) -> List[ContradictionRecord]:
        """Filters contradictions by severity (HIGH, MEDIUM, LOW)."""
        return [r for r in self.records if r.severity == severity]

    def resolve_record(self, record_id: str) -> bool:
        """Marks a contradiction as resolved."""
        for r in self.records:
            if r.id == record_id:
                r.resolved = True
                return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "unresolved_count": len(self.get_unresolved()),
            "high_severity_count": len(self.get_by_severity("HIGH")),
            "medium_severity_count": len(self.get_by_severity("MEDIUM")),
            "low_severity_count": len(self.get_by_severity("LOW")),
            "records": [r.to_dict() for r in self.records]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiscrepancyLedger":
        records = [ContradictionRecord.from_dict(r) for r in data.get("records", [])]
        return cls(records=records)
