"""`uipilot init` through the CLI entrypoint — asserts exit code and friendly summary."""

from __future__ import annotations

from typer.testing import CliRunner

from uipilot.presentation.cli import app

runner = CliRunner()


def test_init_cli_prints_friendly_summary(tmp_path):
    res = runner.invoke(app, ["init", str(tmp_path), "--agent", "claude"])
    assert res.exit_code == 0
    assert "uipilot ready" in res.stdout
    assert ".uipilot/flowmap.config.yaml" in res.stdout
