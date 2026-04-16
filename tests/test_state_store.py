from __future__ import annotations

import json
from pathlib import Path

from councilflow.config.schema import CouncilConfig
from councilflow.state.paths import build_council_paths
from councilflow.state.snapshots import recover_latest_snapshot
from councilflow.state.store import CouncilStateStore


def test_initialize_creates_standard_council_layout(tmp_path: Path) -> None:
    store = CouncilStateStore(tmp_path)
    paths = store.initialize()

    assert paths == build_council_paths(tmp_path)
    assert paths.council_root.is_dir()
    assert paths.plans.is_dir()
    assert paths.discuss.is_dir()
    assert paths.delegations.is_dir()
    assert paths.runs.is_dir()
    assert paths.transcripts.is_dir()
    assert paths.artifacts.is_dir()
    assert paths.state.is_file()


def test_config_round_trip_uses_yaml_file(tmp_path: Path) -> None:
    store = CouncilStateStore(tmp_path)
    store.initialize()

    store.save_config(CouncilConfig(output_language="en"))
    loaded = store.load_config()

    assert loaded.output_language == "en"
    assert loaded.roles.implementer == "claude"


def test_snapshot_recovery_restores_latest_state_and_run(tmp_path: Path) -> None:
    store = CouncilStateStore(tmp_path)
    store.initialize()
    store.write_state(
        {
            "current_phase": "discussion",
            "current_controller": "codex",
        }
    )
    record_path = store.append_run_record(
        "discussion",
        {
            "summary_path": ".council/discuss/disc-001/summary.md",
        },
    )

    snapshot = recover_latest_snapshot(store)

    assert snapshot.state["current_phase"] == "discussion"
    assert snapshot.state["current_controller"] == "codex"
    assert snapshot.latest_run is not None
    assert snapshot.latest_run["kind"] == "discussion"
    assert snapshot.latest_run["payload"]["summary_path"].endswith("summary.md")
    assert snapshot.latest_run_path is not None
    assert snapshot.latest_run_path.endswith(record_path.name)


def test_initialize_recovers_from_corrupted_state_file(tmp_path: Path) -> None:
    store = CouncilStateStore(tmp_path)
    paths = store.initialize()
    paths.state.write_text("", encoding="utf-8")

    store.initialize()

    recovered = json.loads(paths.state.read_text(encoding="utf-8"))

    assert recovered["current_phase"] is None
    assert recovered["current_controller"] is None
    assert recovered["updated_at"] is not None
