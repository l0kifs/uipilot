"""`uipilot init`/`update` through the CLI entrypoint — exit codes and friendly summaries."""

from __future__ import annotations

from typer.testing import CliRunner

from uipilot.infrastructure.scaffold import installed_version
from uipilot.presentation.cli import app

runner = CliRunner()


def test_init_cli_prints_friendly_summary(tmp_path):
    res = runner.invoke(app, ["init", str(tmp_path), "--agent", "claude"])
    assert res.exit_code == 0
    assert "uipilot ready" in res.stdout
    assert ".uipilot/flowmap.config.yaml" in res.stdout


def test_update_cli_reports_refreshed_files_with_versions(tmp_path):
    runner.invoke(app, ["init", str(tmp_path), "--agent", "claude"])
    res = runner.invoke(app, ["update", str(tmp_path)])
    assert res.exit_code == 0
    assert ".claude/skills/uipilot/SKILL.md" in res.stdout
    assert f"v{installed_version()}" in res.stdout


def test_update_cli_exits_2_when_nothing_scaffolded(tmp_path):
    res = runner.invoke(app, ["update", str(tmp_path)])
    assert res.exit_code == 2
    assert "uipilot init" in res.output
