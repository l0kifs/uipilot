"""End-to-end tests: drive the whole stack through the `uipilot` CLI.

Each test invokes the Typer app exactly as a user would, so it exercises the
presentation → application → {domain, infrastructure} chain in one shot. We
assert on exit codes and on the emitted JSON/text payloads (the agent-facing
contract), plus the human table/markdown renderers and every error path.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from uipilot.presentation import cli
from uipilot.presentation.cli import app

runner = CliRunner()

DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo"
PACK = ["--pack", str(DEMO)]


def run(*args: str):
    return runner.invoke(app, PACK + list(args))


# ---------------------------------------------------------------------------
# apps
# ---------------------------------------------------------------------------


def test_apps_json_lists_both_apps():
    result = run("apps")
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["count"] == 2
    assert {a["id"] for a in data["apps"]} == {"console", "portal"}
    console = next(a for a in data["apps"] if a["id"] == "console")
    assert console["auth_entry_flow"] == "console_sign_in"
    assert console["base_url"] == "http://127.0.0.1:4001"


def test_apps_table_format_renders():
    result = runner.invoke(app, PACK + ["--format", "table", "apps"])
    assert result.exit_code == 0
    assert "console" in result.stdout


def test_apps_markdown_format_wraps_json():
    result = runner.invoke(app, PACK + ["--format", "md", "apps"])
    assert result.exit_code == 0
    assert "```json" in result.stdout


# ---------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------


def test_actions_json_all():
    result = run("actions")
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["count"] > 0
    assert any(a["id"] == "act_cs_create_project" for a in data["actions"])


def test_actions_filter_by_transport_api():
    data = json.loads(run("actions", "--transport", "api").stdout)
    assert all(a["transport"] == "api" for a in data["actions"])
    assert any(a["id"] == "api_create_project" for a in data["actions"])


def test_actions_filter_by_risk():
    data = json.loads(run("actions", "--risk", "money-moving").stdout)
    assert {a["id"] for a in data["actions"]} == {"act_pt_submit_withdrawal"}


def test_actions_filter_by_grep_and_app_and_section():
    data = json.loads(run("actions", "--grep", "withdraw").stdout)
    assert any("withdraw" in a["id"] for a in data["actions"])
    scoped = json.loads(run("actions", "--app", "console").stdout)
    assert all(
        a["id"].startswith(("act_cs", "api_create_project", "api_create_cred"))
        or a["transport"] == "api"
        for a in scoped["actions"]
    )
    sect = json.loads(run("actions", "--section", "Sign in").stdout)
    assert any("sign_in" in a["id"] for a in sect["actions"])


def test_actions_table_format():
    result = runner.invoke(app, PACK + ["--format", "table", "actions"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# elements
# ---------------------------------------------------------------------------


def test_elements_json_and_filters():
    data = json.loads(run("elements", "--app", "console").stdout)
    assert all(e["id"].startswith("cs_") for e in data["elements"])
    scoped = json.loads(run("elements", "--action", "act_cs_create_project").stdout)
    ids = {e["id"] for e in scoped["elements"]}
    assert "cs_input_project_name" in ids
    grep = json.loads(run("elements", "--grep", "password").stdout)
    assert any("password" in e["id"] for e in grep["elements"])
    sect = json.loads(run("elements", "--section", "Sign in").stdout)
    assert all(e["id"] for e in sect["elements"])


def test_elements_unknown_action_exits_2():
    result = run("elements", "--action", "act_does_not_exist")
    assert result.exit_code == 2


def test_elements_table_format():
    result = runner.invoke(app, PACK + ["--format", "table", "elements"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# show action / show element
# ---------------------------------------------------------------------------


def test_show_action_ok_and_missing():
    ok = run("show", "action", "act_cs_create_project")
    assert ok.exit_code == 0
    data = json.loads(ok.stdout)
    assert data["id"] == "act_cs_create_project"
    assert data["elements"] and data["steps"]
    assert run("show", "action", "nope").exit_code == 2


def test_show_element_ok_and_missing():
    ok = run("show", "element", "cs_input_email")
    assert ok.exit_code == 0
    data = json.loads(ok.stdout)
    assert data["selector"]["strategy"] == "role"
    assert "getByRole" in data["locator"]
    assert run("show", "element", "nope").exit_code == 2


# ---------------------------------------------------------------------------
# uses
# ---------------------------------------------------------------------------


def test_uses_element_action_flow_and_unknown():
    el = json.loads(run("uses", "cs_input_email").stdout)
    assert el["kind"] == "element" and el["used_by_actions"]
    act = json.loads(run("uses", "act_cs_create_project").stdout)
    assert act["kind"] == "action" and act["used_by_flows"]
    flow = json.loads(run("uses", "console_sign_in").stdout)
    assert flow["kind"] == "flow"
    assert run("uses", "totally_unknown_ref").exit_code == 2


# ---------------------------------------------------------------------------
# flows / flow
# ---------------------------------------------------------------------------


def test_flows_json_and_table():
    data = json.loads(run("flows").stdout)
    assert any(f["id"] == "create_project_with_credential" for f in data["flows"])
    assert runner.invoke(app, PACK + ["--format", "table", "flows"]).exit_code == 0


def test_flow_detail_and_missing():
    ok = run("flow", "portal_withdrawal_via_ui")
    assert ok.exit_code == 0
    data = json.loads(ok.stdout)
    assert data["path"][0]["use"] == "api_onboard"
    assert run("flow", "nope").exit_code == 2


def test_flow_params_manifest_aggregates_and_marks_secrets():
    data = json.loads(run("flow", "create_project_with_credential", "--params").stdout)
    keys = {p["key"] for p in data["params"]}
    # flow-level params AND every action's params, deduped into one manifest
    assert {"project_name", "cred_name", "email", "password", "mfa_code"} <= keys
    assert data["required"] == ["email", "password", "mfa_code"]
    mfa = next(p for p in data["params"] if p["key"] == "mfa_code")
    assert mfa["secret"] is True
    assert mfa["satisfied_by"] == "totp"
    assert mfa["default"] is None  # secret default never echoed


# ---------------------------------------------------------------------------
# path
# ---------------------------------------------------------------------------


def test_path_found_and_not_found():
    found = json.loads(
        run("path", "--from", "act_cs_view_dashboard", "--to", "act_cs_create_credential").stdout
    )
    assert found["found"] is True
    assert found["path"][0] == "act_cs_view_dashboard"
    missing = json.loads(
        run("path", "--from", "act_cs_view_dashboard", "--to", "act_pt_submit_withdrawal").stdout
    )
    assert missing["found"] is False


# ---------------------------------------------------------------------------
# script
# ---------------------------------------------------------------------------


def test_script_flow_default_mcp_format():
    result = run("script", "--flow", "create_project_with_credential")
    assert result.exit_code == 0
    assert '"tool": "browser_navigate"' in result.stdout


def test_script_all_output_formats():
    for fmt, needle in [
        ("steps", '"steps"'),
        ("json", '"flow"'),
        ("pw-test", "@playwright/test"),
        ("playwright-mcp", '"mcp"'),
        ("human", "Flow: create_project_with_credential"),
    ]:
        result = run("script", "--flow", "create_project_with_credential", "--format", fmt)
        assert result.exit_code == 0, (fmt, result.output)
        assert needle in result.stdout


def test_script_human_annotates_capability_and_teardown():
    result = run("script", "--flow", "create_project_with_credential", "--format", "human")
    assert result.exit_code == 0
    assert "minted by capability 'totp'" in result.stdout  # mfa_code, not asked of human
    assert "password = {{password}}  (required — you must supply)" in result.stdout
    assert "Teardown (cleanup afterwards):" in result.stdout


def test_script_json_surfaces_param_capabilities_and_teardown():
    data = json.loads(
        run("script", "--flow", "create_project_with_credential", "--format", "json").stdout
    )
    assert data["param_capabilities"] == {"mfa_code": "totp"}
    td = data["teardown"]
    assert td[0]["id"] == "api_delete_project"
    assert td[0]["args"]["project_id"] == "{{captured.project_id}}"
    # teardown's captured arg does not leak into the flow's param echo
    assert "project_id" not in data["params"]


def test_script_from_path_and_actions_and_set():
    by_path = run(
        "script",
        "--from",
        "act_cs_open_projects",
        "--to",
        "act_cs_create_project",
        "--format",
        "json",
    )
    assert by_path.exit_code == 0
    by_actions = run(
        "script", "--actions", "act_cs_open_projects,act_cs_create_project", "--format", "json"
    )
    assert by_actions.exit_code == 0
    with_set = run(
        "script",
        "--flow",
        "create_project_with_credential",
        "--set",
        "project_name=my-proj",
        "--format",
        "json",
    )
    assert '"my-proj"' in with_set.stdout


def test_script_params_file(tmp_path):
    pf = tmp_path / "params.json"
    pf.write_text(json.dumps({"project_name": "from-file"}))
    result = run(
        "script",
        "--flow",
        "create_project_with_credential",
        "--params",
        str(pf),
        "--format",
        "json",
    )
    assert result.exit_code == 0
    assert "from-file" in result.stdout


def test_script_bad_set_is_rejected():
    result = run("script", "--flow", "create_project_with_credential", "--set", "noequals")
    assert result.exit_code != 0


def test_script_needs_a_target():
    assert run("script").exit_code == 2


def test_script_unknown_flow_exits_2():
    assert run("script", "--flow", "ghost_flow").exit_code == 2


def test_script_refuse_destructive_and_batch():
    refused = run(
        "script", "--flow", "portal_withdrawal_via_ui", "--refuse-destructive", "--format", "json"
    )
    assert refused.exit_code == 0
    assert "refused" in json.loads(refused.stdout)
    batched = run("script", "--flow", "portal_withdrawal_via_ui", "--batch", "--format", "json")
    assert batched.exit_code == 0


def test_script_skip_auth_drops_auth_precondition():
    data = json.loads(
        run(
            "script",
            "--from",
            "act_cs_open_projects",
            "--to",
            "act_cs_create_project",
            "--skip-auth",
            "--format",
            "json",
        ).stdout
    )
    assert all(p["kind"] != "auth" for p in data["preconditions"])


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_clean_exits_zero():
    result = run("validate")
    assert result.exit_code == 0
    assert json.loads(result.stdout)["errors"] == 0


def test_validate_scoped_to_app():
    result = run("validate", "--app", "console")
    assert result.exit_code == 0


def test_validate_table_format():
    assert runner.invoke(app, PACK + ["--format", "table", "validate"]).exit_code == 0


def test_validate_broken_pack_exits_1(tmp_path):
    import shutil

    shutil.copytree(DEMO, tmp_path, dirs_exist_ok=True)
    p = tmp_path / "data" / "console.app.yaml"
    doc = yaml.safe_load(p.read_text())
    doc["actions"]["act_cs_create_project"]["elements"].append("cs_ghost")
    p.write_text(yaml.safe_dump(doc))
    result = runner.invoke(app, ["--pack", str(tmp_path), "validate"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["errors"] >= 1


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def test_verify_by_flow_app_action():
    by_flow = json.loads(run("verify", "--flow", "create_project_with_credential").stdout)
    assert by_flow["read_only"] is True
    by_app = json.loads(run("verify", "--app", "console").stdout)
    assert by_app["mode"] == "probe"
    by_action = json.loads(run("verify", "--action", "act_cs_create_project").stdout)
    assert by_action["scope"]["action"] == "act_cs_create_project"


def test_verify_drive_and_allow_gated():
    drive = json.loads(run("verify", "--flow", "portal_withdrawal_via_ui", "--drive").stdout)
    assert drive["mode"] == "drive" and drive["refused_gated"]
    allowed = json.loads(
        run("verify", "--flow", "portal_withdrawal_via_ui", "--drive", "--allow-gated").stdout
    )
    assert allowed["refused_gated"] == []


def test_verify_requires_a_scope():
    assert run("verify").exit_code == 2


def test_verify_unknown_flow_exits_2():
    assert run("verify", "--flow", "ghost").exit_code == 2


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------


def test_emit_pom_default():
    result = run("emit")
    assert result.exit_code == 0
    assert "class ConsolePage" in result.stdout
    assert "DO NOT EDIT" in result.stdout


def test_emit_pom_scoped_to_app():
    result = run("emit", "--app", "portal")
    assert result.exit_code == 0
    assert "class PortalPage" in result.stdout


def test_emit_pw_test_needs_flow():
    assert run("emit", "--format", "pw-test").exit_code == 2
    ok = run("emit", "--format", "pw-test", "--flow", "create_project_with_credential")
    assert ok.exit_code == 0
    assert "@playwright/test" in ok.stdout


def test_emit_unknown_format_exits_2():
    assert run("emit", "--format", "bogus").exit_code == 2


# ---------------------------------------------------------------------------
# capabilities
# ---------------------------------------------------------------------------


def test_capabilities_list_and_check():
    listing = json.loads(run("capabilities").stdout)
    assert {c["key"] for c in listing["capabilities"]} == {"totp", "storage_state"}
    checked = json.loads(run("capabilities", "--check").stdout)
    assert all(c["error"] is None for c in checked["capabilities"])


# ---------------------------------------------------------------------------
# import-md (no --pack; writes a fresh seed)
# ---------------------------------------------------------------------------


def test_import_md_command(tmp_path):
    md = tmp_path / "map.md"
    md.write_text("act_ex_do_thing uses ex_btn_thing and ex_input_thing.")
    out = tmp_path / "seed"
    result = runner.invoke(app, ["import-md", str(md), "--out", str(out)])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["structured"] is False
    assert (out / "flowmap.config.yaml").exists()


# ---------------------------------------------------------------------------
# pack resolution (default pack + no-pack error)
# ---------------------------------------------------------------------------


def test_no_args_shows_help():
    # no_args_is_help=True prints usage and exits non-zero
    result = runner.invoke(app, [])
    assert result.exit_code == 2
    assert "Usage" in result.output or "Commands" in result.output


def test_env_var_selects_pack(monkeypatch):
    monkeypatch.setenv("UIPILOT_PACK", str(DEMO))
    result = runner.invoke(app, ["apps"])
    assert result.exit_code == 0
    assert "console" in result.stdout


def test_no_pack_found_exits_2(tmp_path, monkeypatch):
    monkeypatch.delenv("UIPILOT_PACK", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_BUNDLED_EXAMPLE", tmp_path / "nonexistent")
    result = runner.invoke(app, ["apps"])
    assert result.exit_code == 2


def test_bad_pack_dir_exits_2(tmp_path):
    result = runner.invoke(app, ["--pack", str(tmp_path), "apps"])
    assert result.exit_code == 2


def test_dotuipilot_pack_autodetected(tmp_path, monkeypatch):
    import shutil

    shutil.copytree(DEMO, tmp_path / ".uipilot", dirs_exist_ok=True)
    monkeypatch.delenv("UIPILOT_PACK", raising=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["apps"])
    assert result.exit_code == 0
    assert "console" in result.stdout
