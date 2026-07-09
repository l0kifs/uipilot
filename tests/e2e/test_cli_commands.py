"""CLI smoke tests — drive the app through its Typer entrypoint and assert exit/stdout."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from uipilot.presentation.cli import app

runner = CliRunner()

_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
PACK = ["--pack", str(_ROOT / "examples" / "demo")]


def test_cli_validate_exit_zero():
    result = runner.invoke(app, [*PACK, "validate"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["errors"] == 0


def test_cli_apps_json():
    result = runner.invoke(app, [*PACK, "apps"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert {a["id"] for a in data["apps"]} == {"console", "portal"}


def test_cli_script_flow():
    result = runner.invoke(app, [*PACK, "script", "--flow", "create_project_with_credential"])
    assert result.exit_code == 0
    assert '"tool": "browser_navigate"' in result.stdout


def test_cli_plan_flow_is_one_shot():
    result = runner.invoke(app, [*PACK, "plan", "--flow", "create_project_with_credential"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    # app + guard + manifest + compiled script, all in one call.
    assert data["flow"] == "create_project_with_credential"
    assert data["app"]["id"] == "console"
    assert data["app"]["base_url"]
    assert "guard" in data
    assert isinstance(data["params_manifest"], list)
    assert data["script"]["executor"]["tool_prefix"] == "mcp__playwright__"
    assert data["script"]["steps"]


def test_cli_plan_unknown_flow_exit_2():
    result = runner.invoke(app, [*PACK, "plan", "--flow", "does_not_exist"])
    assert result.exit_code == 2


def test_cli_path_not_found_reports_reason():
    result = runner.invoke(
        app, [*PACK, "path", "--from", "act_cs_view_dashboard", "--to", "act_pt_submit_withdrawal"]
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["found"] is False


def test_cli_uses_unknown_ref_errors():
    result = runner.invoke(app, [*PACK, "uses", "nope_nothing"])
    assert result.exit_code == 2
