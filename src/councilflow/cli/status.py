"""CLI entrypoint for inspecting current CouncilFlow state."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import typer

from councilflow.controller.host_context import detect_controller
from councilflow.models.run_record import RunRecord
from councilflow.state.store import CouncilStateStore
from councilflow.utils.lang import emit_console_text, emit_response, resolve_output_language

DEFAULT_PROJECT_ROOT = Path(".")
PROJECT_ROOT_OPTION = typer.Option(
    DEFAULT_PROJECT_ROOT,
    "--project-root",
    resolve_path=True,
    file_okay=False,
    dir_okay=True,
    help="Project root used to resolve .council state and artifacts.",
)
RECENT_OPTION = typer.Option(
    30,
    "--recent",
    min=1,
    help=(
        "Window in days for aggregating routing / discussion analytics "
        "(default 30). Entries whose timestamp is older than now - N days "
        "are excluded from the distribution summaries."
    ),
)


def _parse_iso_timestamp(value: Any) -> datetime | None:
    """Best-effort ISO-8601 parsing; return None when the value is missing or invalid."""

    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _collect_routing_distribution(
    project_root: Path, cutoff: datetime
) -> dict[str, Any]:
    """Scan .council/runs/**/routing.json and summarize role → model hits.

    Returns a dict with total record count and per-role mapping of
    ``model → count`` for records whose timestamp is within the window.
    """

    runs_root = project_root / ".council" / "runs"
    if not runs_root.is_dir():
        return {"total_records": 0, "roles": {}, "source": str(runs_root)}

    total = 0
    by_role: dict[str, dict[str, int]] = {}
    for log_file in runs_root.rglob("routing.json"):
        try:
            data = json.loads(log_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, list):
            continue
        for record in data:
            if not isinstance(record, dict):
                continue
            timestamp = _parse_iso_timestamp(record.get("timestamp"))
            if timestamp is not None and timestamp < cutoff:
                continue
            role = record.get("role")
            model = record.get("primary_model") or "<no_match>"
            if not isinstance(role, str):
                continue
            role_bucket = by_role.setdefault(role, {})
            role_bucket[model] = role_bucket.get(model, 0) + 1
            total += 1

    return {"total_records": total, "roles": by_role, "source": str(runs_root)}


def _collect_convergence_distribution(
    project_root: Path, cutoff: datetime
) -> dict[str, Any]:
    """Scan .council/discuss/**/record.json for per-run convergence summary.

    Returns average rounds completed and distribution of ended_reason
    (``converged`` / ``max_rounds_reached`` / etc.) across records in
    the window.
    """

    discuss_root = project_root / ".council" / "discuss"
    if not discuss_root.is_dir():
        return {
            "total_records": 0,
            "average_rounds_completed": 0.0,
            "ended_reason_distribution": {},
            "source": str(discuss_root),
        }

    total = 0
    rounds_sum = 0
    ended_reasons: dict[str, int] = {}
    for record_file in discuss_root.rglob("record.json"):
        try:
            data = json.loads(record_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        timestamp = _parse_iso_timestamp(data.get("created_at"))
        if timestamp is not None and timestamp < cutoff:
            continue
        rounds_completed = data.get("completed_rounds") or data.get("rounds_completed") or 0
        if isinstance(rounds_completed, (int, float)):
            rounds_sum += int(rounds_completed)
        ended_reason = data.get("ended_reason") or "<unknown>"
        if isinstance(ended_reason, str):
            ended_reasons[ended_reason] = ended_reasons.get(ended_reason, 0) + 1
            total += 1

    average = (rounds_sum / total) if total else 0.0
    return {
        "total_records": total,
        "average_rounds_completed": round(average, 2),
        "ended_reason_distribution": ended_reasons,
        "source": str(discuss_root),
    }


def status(
    project_root: Path = PROJECT_ROOT_OPTION,
    recent: int = RECENT_OPTION,
) -> None:
    """Report current controller, language, and latest discussion/delegation runs.

    Adds (0.1.3+) ``routing_distribution`` and ``convergence_distribution``
    segments summarizing the last ``--recent`` days of ``.council/runs/``
    routing audit records and ``.council/discuss/`` discussion records.
    Both segments degrade gracefully when their source dirs are missing
    or empty — the ``total_records`` field is ``0`` rather than a crash.
    """

    store = CouncilStateStore(project_root)
    store.initialize()
    config = store.load_config()
    output_language = resolve_output_language(config.output_language)
    controller = detect_controller(config=config).controller.value
    run_records = [
        RunRecord.model_validate(store.load_run_record(path))
        for path in store.list_run_records()
    ]

    recent_discussion = next(
        (record for record in reversed(run_records) if record.kind == "discussion"),
        None,
    )
    recent_delegation = next(
        (record for record in reversed(run_records) if record.kind == "delegation"),
        None,
    )

    cutoff = datetime.now(tz=UTC) - timedelta(days=recent)
    routing_distribution = _collect_routing_distribution(project_root, cutoff)
    convergence_distribution = _collect_convergence_distribution(project_root, cutoff)

    emit_console_text(
        emit_response(
            data={
                "current_controller": controller,
                "output_language": output_language,
                "state": store.read_state(),
                "recent_discussion": (
                    recent_discussion.model_dump(mode="json")
                    if recent_discussion is not None
                    else None
                ),
                "recent_delegation": (
                    recent_delegation.model_dump(mode="json")
                    if recent_delegation is not None
                    else None
                ),
                "routing_distribution": routing_distribution,
                "convergence_distribution": convergence_distribution,
                "recent_window_days": recent,
            },
            meta={
                "command": "status",
                "run_record_count": len(run_records),
            },
        )
    )
