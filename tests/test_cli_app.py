from __future__ import annotations

from typer.testing import CliRunner

from councilflow.cli.app import app

runner = CliRunner()


def test_help_output_is_available() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "version" in result.output


def test_version_command_reports_package_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.output.strip() == "0.1.0"
