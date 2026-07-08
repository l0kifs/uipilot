from __future__ import annotations

from uipilot.domain.compiler import compile_actions, compile_flow, compile_path


def _ops(script):
    return [s.op for s in script.steps]


def test_snapshot_inserted_only_on_dom_change(pack, ctx):
    s = compile_flow(pack, ctx, "create_project_with_credential")
    ops = _ops(s)
    # first interacting step is preceded by a snapshot
    assert ops[0] == "navigate" and ops[1] == "snapshot"
    # no two snapshots in a row (defensive snapshots avoided)
    for a, b in zip(ops, ops[1:]):
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
