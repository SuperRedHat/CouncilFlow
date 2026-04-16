"""Recovery helpers for the latest CouncilFlow local state snapshot."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from councilflow.state.store import CouncilStateStore


class RecoverySnapshot(BaseModel):
    """Recovered state plus the most recent run record, if available."""

    state: dict[str, Any]
    latest_run_path: str | None = None
    latest_run: dict[str, Any] | None = None


def recover_latest_snapshot(store: CouncilStateStore) -> RecoverySnapshot:
    """Recover the current state and the latest persisted run record."""

    state = store.read_state()
    run_records = store.list_run_records()
    if not run_records:
        return RecoverySnapshot(state=state)

    latest_path = run_records[-1]
    return RecoverySnapshot(
        state=state,
        latest_run_path=str(latest_path.relative_to(store.paths.project_root)),
        latest_run=store.load_run_record(latest_path),
    )

