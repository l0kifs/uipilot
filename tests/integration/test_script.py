from __future__ import annotations

import itertools
import shutil
from pathlib import Path

import yaml

from uipilot.domain.compiler import compile_actions, compile_flow, compile_path
from uipilot.domain.templating import RuntimeContext
from uipilot.infrastructure.pack_loader import load_pack

_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
DEMO = _ROOT / "examples" / "demo"


def _ops(script):
    return [s.op for s in script.steps]


def _navs(script):
    return [s.value for s in script.steps if s.op == "navigate"]


def _pack_with_templated_route(tmp_path):
    """Demo pack + an action whose route templates a param (/projects/{{project_id}})."""
    shutil.copytree(DEMO, tmp_path, dirs_exist_ok=True)
    ap = tmp_path / "data" / "console.app.yaml"
    doc = yaml.safe_load(ap.read_text())
    doc["elements"]["cs_text_project_hdr"] = {
        "type": "text",
        "section": "Project",
        "selector": {"strategy": "role", "role": "heading", "name": "Project detail"},
        "purpose": "Project detail header",
    }
    doc["actions"]["act_cs_open_project"] = {
        "purpose": "Open a project by id.",
        "route": "/projects/{{project_id}}",
        "risk": "low",
        "elements": ["cs_text_project_hdr"],
        "params": [{"key": "project_id", "type": "string", "required": True}],
        "steps": [{"op": "wait_for", "element": "cs_text_project_hdr"}],
    }
    ap.write_text(yaml.safe_dump(doc))

    fp = tmp_path / "data" / "flows.yaml"
    fdoc = yaml.safe_load(fp.read_text())
    fdoc["flows"]["visit_two_projects"] = {
        "app": "console",
        "path": [
            {"action": "act_cs_open_project", "as": "a", "params": {"project_id": "p1"}},
            {"action": "act_cs_open_project", "as": "b", "params": {"project_id": "p2"}},
        ],
    }
    fdoc["flows"]["visit_same_project_twice"] = {
        "app": "console",
        "path": [
            {"action": "act_cs_open_project", "as": "a", "params": {"project_id": "same"}},
            {"action": "act_cs_open_project", "as": "b", "params": {"project_id": "same"}},
        ],
    }
    fp.write_text(yaml.safe_dump(fdoc))

    pack = load_pack(tmp_path)
    ctx = RuntimeContext(pack.config, env={"TEST_ENTITY_PREFIX": "demo"})
    return pack, ctx


def test_route_param_substituted(tmp_path):
    pack, ctx = _pack_with_templated_route(tmp_path)
    s = compile_actions(
        pack, ctx, ["act_cs_open_project"], skip_auth=True, overrides={"project_id": "abc123"}
    )
    assert _navs(s) == ["http://127.0.0.1:4001/projects/abc123"]
    assert "project_id" not in s.params_required


def test_route_param_required_when_missing(tmp_path):
    pack, ctx = _pack_with_templated_route(tmp_path)
    s = compile_actions(pack, ctx, ["act_cs_open_project"], skip_auth=True)
    # Reported required, and the placeholder is preserved for the agent to fill.
    assert "project_id" in s.params_required
    assert _navs(s) == ["http://127.0.0.1:4001/projects/{{project_id}}"]


def test_route_distinct_ids_not_deduped(tmp_path):
    pack, ctx = _pack_with_templated_route(tmp_path)
    s = compile_flow(pack, ctx, "visit_two_projects", skip_auth=True)
    assert _navs(s) == [
        "http://127.0.0.1:4001/projects/p1",
        "http://127.0.0.1:4001/projects/p2",
    ]


def test_route_same_resolved_url_deduped(tmp_path):
    pack, ctx = _pack_with_templated_route(tmp_path)
    s = compile_flow(pack, ctx, "visit_same_project_twice", skip_auth=True)
    assert _navs(s) == ["http://127.0.0.1:4001/projects/same"]


def test_snapshot_inserted_only_on_dom_change(pack, ctx):
    s = compile_flow(pack, ctx, "create_project_with_credential")
    ops = _ops(s)
    # first interacting step is preceded by a snapshot
    assert ops[0] == "navigate" and ops[1] == "snapshot"
    # no two snapshots in a row (defensive snapshots avoided)
    for a, b in itertools.pairwise(ops):
        assert not (a == "snapshot" and b == "snapshot")


def test_secret_never_echoed_but_listed_required(pack, ctx):
    s = compile_flow(pack, ctx, "create_project_with_credential")
    assert s.params["password"] == "{{password}}"
    assert "password" in s.params_required
    assert "mfa_code" in s.params_required


def test_secret_materialises_only_in_consuming_step(pack, ctx):
    s = compile_flow(
        pack,
        ctx,
        "create_project_with_credential",
        overrides={"password": "hunter2", "mfa_code": "000111"},
    )
    # echoed header still hides the secret
    assert s.params["password"] == "{{password}}"
    # but the consuming fill step carries the real value
    fills = [st for st in s.steps if st.element == "cs_input_password"]
    assert fills and fills[0].value == "hunter2"


def test_default_token_expansion(pack, ctx):
    s = compile_flow(pack, ctx, "create_project_with_credential")
    assert s.params["project_name"].startswith("demo-project-")


def test_auth_prepended_when_absent(pack, ctx):
    s = compile_path(pack, ctx, "act_cs_open_projects", "act_cs_create_project")
    kinds = [p["kind"] for p in s.preconditions]
    assert "auth" in kinds


def test_auth_skipped_when_signin_in_path(pack, ctx):
    s = compile_flow(pack, ctx, "create_project_with_credential")
    assert all(p["kind"] != "auth" for p in s.preconditions)


def test_api_setup_routed_to_preconditions(pack, ctx):
    s = compile_flow(pack, ctx, "portal_withdrawal_via_ui")
    ids = [p.get("id") for p in s.preconditions]
    assert "api_create_wallet" in ids
    assert s.crosschecks[0]["id"] == "api_assert_operation"


def test_capture_bridges_into_crosscheck_args(pack, ctx):
    s = compile_flow(pack, ctx, "portal_withdrawal_via_ui")
    args = s.crosschecks[0]["args"]
    assert args["operation_id"] == "{{captured.operation_id}}"


def test_risk_max_and_gate(pack, ctx):
    s = compile_flow(pack, ctx, "portal_withdrawal_via_ui")
    assert s.risk_max == "money-moving"
    gated = compile_flow(pack, ctx, "portal_withdrawal_via_ui", refuse_destructive=True)
    assert gated.refused and gated.steps == []


def test_navigation_deduped(pack, ctx):
    # onboard_two_projects creates two projects on the same /projects route
    s = compile_flow(pack, ctx, "onboard_two_projects")
    navs = [st for st in s.steps if st.op == "navigate"]
    routes = [st.value for st in navs]
    assert len(routes) == len(set(routes)), f"duplicate navigations: {routes}"


def test_alias_namespaces_captures(pack, ctx):
    s = compile_flow(pack, ctx, "onboard_two_projects")
    caps = [st.capture for st in s.steps if st.op == "capture"]
    assert "primary.project_id" in caps
    assert "secondary.project_id" in caps


def test_batch_collapses_fills(pack, ctx):
    s = compile_flow(pack, ctx, "portal_withdrawal_via_ui", batch=True)
    assert any(st.op == "fill_form" for st in s.steps)


def test_compile_actions_adhoc(pack, ctx):
    s = compile_actions(pack, ctx, ["act_cs_open_projects", "act_cs_create_project"])
    assert s.name == "adhoc"
    assert any(st.op == "click" for st in s.steps)


def test_wait_for_element_derives_text(pack, ctx):
    s = compile_flow(pack, ctx, "create_project_with_credential")
    waits = [st for st in s.steps if st.op == "wait_for" and st.mcp]
    assert any(w.mcp["args"].get("text") for w in waits)


# --- auth precondition skip_if (from the entry flow's guard) ----------------


def test_auth_skip_if_from_guard(pack, ctx):
    # console_sign_in guards on {expect: {text: "Current session"}}; that marker
    # must ride into the prepended auth precondition so the agent can skip-check.
    s = compile_path(pack, ctx, "act_cs_open_projects", "act_cs_create_project")
    auth = next(p for p in s.preconditions if p["kind"] == "auth")
    assert auth["skip_if"] == {"text": "Current session"}


def test_auth_no_skip_if_when_entry_flow_unguarded(pack, ctx):
    # portal_sign_in has no guard → no skip_if key (agent must actually sign in).
    s = compile_path(pack, ctx, "act_pt_open_wallet_detail", "act_pt_submit_withdrawal")
    auth = next(p for p in s.preconditions if p["kind"] == "auth")
    assert "skip_if" not in auth


# --- executor tool-prefix (playwright-mcp output only) ----------------------


def test_executor_prefix_only_in_mcp_output(pack, ctx):
    s = compile_flow(pack, ctx, "create_project_with_credential")
    assert s.as_dict(with_mcp=True)["executor"]["tool_prefix"] == "mcp__playwright__"
    assert "executor" not in s.as_dict(with_mcp=False)


# --- params_satisfiable (env-backed secret defaults) ------------------------


def _pack_with_env_secret(tmp_path):
    """Demo pack + an env-backed secret token and a required secret param whose
    default draws from it (models a sign-in password wired to `.uipilot/.env`)."""
    shutil.copytree(DEMO, tmp_path, dirs_exist_ok=True)
    cfg = tmp_path / "flowmap.config.yaml"
    cdoc = yaml.safe_load(cfg.read_text())
    cdoc.setdefault("tokens", {})["portal_secret"] = {"from": "env", "name": "PORTAL_SECRET"}
    cfg.write_text(yaml.safe_dump(cdoc))

    ap = tmp_path / "data" / "console.app.yaml"
    adoc = yaml.safe_load(ap.read_text())
    adoc["actions"]["act_cs_sign_in_submit"]["params"].append(
        {"key": "api_secret", "type": "secret", "required": True, "default": "{{portal_secret}}"}
    )
    ap.write_text(yaml.safe_dump(adoc))
    return load_pack(tmp_path)


def test_params_satisfiable_when_env_present(tmp_path):
    pack = _pack_with_env_secret(tmp_path)
    ctx = RuntimeContext(pack.config, env={"PORTAL_SECRET": "s3cr3t"})
    s = compile_flow(pack, ctx, "create_project_with_credential")
    # Still required (never materialised from a default), but flagged env-satisfiable.
    assert "api_secret" in s.params_required
    assert s.params_satisfiable["api_secret"] == {"source": "env:PORTAL_SECRET", "present": True}
    # The value is never echoed.
    assert s.params["api_secret"] == "{{api_secret}}"


def test_params_satisfiable_marks_env_absent(tmp_path):
    pack = _pack_with_env_secret(tmp_path)
    ctx = RuntimeContext(pack.config, env={})
    s = compile_flow(pack, ctx, "create_project_with_credential")
    assert s.params_satisfiable["api_secret"] == {"source": "env:PORTAL_SECRET", "present": False}


def test_plain_secret_without_env_default_not_satisfiable(pack, ctx):
    # The demo password secret has no default → not env-satisfiable, only required.
    s = compile_flow(pack, ctx, "create_project_with_credential")
    assert "password" in s.params_required
    assert "password" not in s.params_satisfiable
