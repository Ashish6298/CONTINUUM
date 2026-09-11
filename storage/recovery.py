"""
Project Continuum - State Corruption Detection & Safe Auto-Recovery
===================================================================
Milestone 7 - Phase 17: Git Hooks & Persistent State Management.
Validates active state JSON integrity, detects schema or byte-level corruption,
and safely restores from the most recent valid history snapshot.
"""

from pathlib import Path
from typing import Optional, Tuple

from core.schema import validate_canonical_state_dict
from core.serializer import CanonicalStateSerializer, StateSerializationError, StateValidationError
from core.state_models import CanonicalProjectState
from storage.manager import ContinuumStorageManager
from storage.models import RecoveryResult


class StateRecoveryManager:
    """
    Guarantees state recoverability:
    1. Audits active state for corruption.
    2. Recovers cleanly from the latest uncorrupted history snapshot if damaged.
    """

    def __init__(self, storage_manager: ContinuumStorageManager):
        self._storage = storage_manager

    def verify_active_state_integrity(self) -> Tuple[bool, Optional[str]]:
        """
        Verifies if active state file is valid and compliant with schema.
        Returns (is_valid, error_reason).
        """
        if not self._storage.state_exists():
            return False, "Active state file does not exist."

        try:
            state = self._storage.load_state(validate=True)
            return True, None
        except (StateSerializationError, StateValidationError, Exception) as e:
            return False, str(e)

    def recover_corrupted_state(self) -> RecoveryResult:
        """
        Attempts to recover from state corruption by finding the most recent
        valid snapshot in .continuum/history/ and restoring it to state.json.
        """
        is_valid, error_reason = self.verify_active_state_integrity()
        if is_valid:
            return RecoveryResult(
                success=True,
                recovered_from=str(self._storage.active_state_file),
                state_restored=False,
                details={"status": "Active state is healthy; no recovery needed."}
            )

        # Active state is corrupted: inspect history snapshots
        snapshots = self._storage.list_history_snapshots()
        if not snapshots:
            # Check backup directory
            backup_file = self._storage.backup_dir / "state.json.bak"
            if backup_file.exists():
                try:
                    state = CanonicalStateSerializer.load_from_file(backup_file, validate=True)
                    self._storage.save_state(state, create_history_snapshot=False)
                    return RecoveryResult(
                        success=True,
                        recovered_from=str(backup_file),
                        state_restored=True,
                        details={"restored_from": "backup"}
                    )
                except Exception:
                    pass

            return RecoveryResult(
                success=False,
                error_message=f"Active state corrupted ({error_reason}), and no valid history snapshots exist."
            )

        # Search snapshots for the newest valid one
        for snapshot_path in snapshots:
            try:
                state = CanonicalStateSerializer.load_from_file(snapshot_path, validate=True)
                # Found valid snapshot! Restore as active state
                self._storage.save_state(state, create_history_snapshot=False)
                return RecoveryResult(
                    success=True,
                    recovered_from=str(snapshot_path),
                    state_restored=True,
                    details={"snapshot_name": snapshot_path.name, "corrupted_reason": error_reason}
                )
            except Exception:
                continue

        return RecoveryResult(
            success=False,
            error_message=f"All {len(snapshots)} history snapshots were tested and none were valid."
        )
