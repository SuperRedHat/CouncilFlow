"""CLI entrypoint for inspecting current CouncilFlow state."""

from __future__ import annotations

from pathlib import Path

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


def status(project_root: Path = PROJECT_ROOT_OPTION) -> None:
    """Report current controller, language, and latest discussion/delegation runs."""

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
            },
            meta={
                "command": "status",
                "run_record_count": len(run_records),
            },
        )
    )
