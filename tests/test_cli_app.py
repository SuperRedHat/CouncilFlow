from __future__ import annotations

import inspect

from typer.testing import CliRunner

from councilflow.cli.app import app, main

runner = CliRunner()


def test_help_output_is_available() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "version" in result.output


def test_version_command_reports_package_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.output.strip() == "0.1.1"


def test_main_disables_windows_glob_expansion() -> None:
    """TASK-059: Click on Windows otherwise pre-expands argv globs, turning
    patterns like ``--writable-glob 'src/features/**'`` into a list of already
    existing filesystem entries before ExecutionGuardrails ever sees them."""

    source = inspect.getsource(main)
    assert "windows_expand_args=False" in source, (
        "council CLI must opt out of Click's Windows argv glob expansion."
    )


def test_main_runs_configure_logging_before_app(monkeypatch) -> None:
    """Structured logging must be wired up before any subcommand dispatches,
    so TASK-051's logger calls have the expected level when exec reaches the
    orchestrator."""

    calls: list[str] = []

    def fake_configure() -> None:
        calls.append("configure_logging")

    def fake_app(**kwargs: object) -> None:
        calls.append(f"app(windows_expand_args={kwargs.get('windows_expand_args')})")

    monkeypatch.setattr("councilflow.utils.logging.configure_logging", fake_configure)
    monkeypatch.setattr("councilflow.cli.app.app", fake_app)

    main()

    assert calls == ["configure_logging", "app(windows_expand_args=False)"]
