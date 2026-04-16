"""CLI entrypoint for synthesizing existing artifacts."""

from __future__ import annotations

from pathlib import Path

import typer

from councilflow.state.store import CouncilStateStore
from councilflow.utils.lang import emit_console_text, emit_response, resolve_output_language

DEFAULT_PROJECT_ROOT = Path(".")
ARTIFACT_OPTION = typer.Option(
    ...,
    "--artifact",
    resolve_path=True,
    exists=True,
    file_okay=True,
    dir_okay=False,
    help="Repeat to provide discussion or delegation artifacts to synthesize.",
)
PROJECT_ROOT_OPTION = typer.Option(
    DEFAULT_PROJECT_ROOT,
    "--project-root",
    resolve_path=True,
    file_okay=False,
    dir_okay=True,
    help="Project root used to resolve .council state and language settings.",
)


def synthesize(
    artifact: list[Path] = ARTIFACT_OPTION,
    project_root: Path = PROJECT_ROOT_OPTION,
) -> None:
    """Combine persisted artifacts into a single synthesized view."""

    store = CouncilStateStore(project_root)
    store.initialize()
    output_language = resolve_output_language(store.load_config().output_language)
    sources = [str(path.resolve().relative_to(project_root.resolve())) for path in artifact]
    synthesis = "\n\n".join(
        [
            f"## {path.name}\n{path.read_text(encoding='utf-8').strip()}"
            for path in artifact
        ]
    )

    emit_console_text(
        emit_response(
            data={
                "output_language": output_language,
                "sources": sources,
                "synthesis": synthesis,
            },
            meta={
                "command": "synthesize",
                "artifact_count": len(artifact),
            },
        )
    )
