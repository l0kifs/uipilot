from __future__ import annotations

import pytest

from uipilot.domain.errors import PackError
from uipilot.domain.model import Selector
from uipilot.domain.templating import RuntimeContext, resolve_template
from uipilot.infrastructure.pack_loader import load_pack


def test_pack_loads_apps_elements_actions_flows(pack):
    assert set(pack.apps) == {"console", "portal"}
    assert "act_cs_create_project" in pack.actions
    assert "cs_btn_project_create" in pack.elements
    assert "create_project_with_credential" in pack.flows


def test_api_actions_parsed_with_transport(pack):
    api = pack.action("api_create_project")
    assert api.is_api
    assert api.call == "factories.project:create_project"
    assert api.route is None
    assert "project" in api.provides


def test_element_app_inferred_from_file(pack):
    assert pack.element("cs_btn_project_create").app == "console"
    assert pack.element("pt_btn_withdraw").app == "portal"


def test_flow_path_entry_shapes(pack):
    flow = pack.flow("portal_withdrawal_via_ui")
    first = flow.path[0]
    assert first.use == "api_onboard" and first.alias == "acct"
    withdrawal = [p for p in flow.path if p.action == "act_pt_sign_in"][0]
    assert withdrawal.params["credential_id"] == "{{acct.credential_id}}"


def test_missing_config_raises(tmp_path):
    with pytest.raises(PackError):
        load_pack(tmp_path)


def test_selector_locator_rendering():
    role = Selector(strategy="role", role="button", name="Create")
    assert role.to_locator() == "getByRole('button', { name: 'Create' })"
    scoped = Selector(strategy="role", role="button", name="Create", scope="dialog")
    assert scoped.to_locator() == "getByRole('dialog').getByRole('button', { name: 'Create' })"


def test_token_resolution_env_and_counter():
    from uipilot.domain.model import Config, Token

    cfg = Config(
        pack="p",
        apps=[],
        tokens={
            "prefix": Token("prefix", "env", name="TEST_ENTITY_PREFIX", default="fallback"),
            "seq": Token("seq", "counter"),
        },
    )
    ctx = RuntimeContext(cfg, env={"TEST_ENTITY_PREFIX": "acme"})
    assert ctx.token("prefix") == "acme"
    # counter is stable within a run (cached on first access)
    assert ctx.token("seq") == ctx.token("seq")


def test_resolve_template_leaves_captures_and_unknowns():
    out, unresolved = resolve_template("{{name}}-{{captured.x}}", {"name": "bob"}, None)
    assert out == "bob-{{captured.x}}"
    assert unresolved == []
    out2, unresolved2 = resolve_template("{{missing}}", {}, None)
    assert out2 == "{{missing}}" and unresolved2 == ["missing"]
