"""Integration tests for the application layer.

These call the use-case functions in :mod:`uipilot.application.service`
directly (not through the CLI), verifying that the layer correctly wires
infrastructure loading to domain services and returns domain objects / plain
data — the contract every front-end depends on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uipilot.application import service
from uipilot.application.service import PackContext, open_pack

_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
DEMO = _ROOT / "examples" / "demo"


def test_open_pack_builds_runtime_context():
    pctx = open_pack(str(DEMO), env={"TEST_ENTITY_PREFIX": "demo"})
    assert isinstance(pctx, PackContext)
    assert pctx.pack.config.pack == "demo"
    # env is threaded into token resolution
    assert pctx.runtime.token("prefix") == "demo"


def test_open_pack_defaults_to_os_environ(monkeypatch):
    monkeypatch.setenv("TEST_ENTITY_PREFIX", "envval")

    pctx = open_pack(DEMO)
    assert pctx.runtime.token("prefix") == "envval"


@pytest.fixture
def pctx(pack):
    from uipilot.domain.templating import RuntimeContext

    return PackContext(
        pack=pack, runtime=RuntimeContext(pack.config, env={"TEST_ENTITY_PREFIX": "demo"})
    )


# --- queries ---------------------------------------------------------------


def test_filter_actions_every_filter(pctx):
    assert service.filter_actions(pctx, app="console")
    assert service.filter_actions(pctx, transport="api")
    assert service.filter_actions(pctx, risk="money-moving")
    assert service.filter_actions(pctx, grep="withdraw")
    assert service.filter_actions(pctx, section="Sign in")
    # non-matching filters return empty
    assert service.filter_actions(pctx, risk="does-not-exist") == []


def test_filter_elements_scoped_by_action(pctx):
    els = service.filter_elements(pctx, action="act_cs_create_project")
    assert {e.id for e in els} >= {"cs_input_project_name"}
    assert service.filter_elements(pctx, app="portal", grep="amount")
    assert service.filter_elements(pctx, section="Sign in")


def test_filter_elements_unknown_action_raises(pctx):
    with pytest.raises(KeyError):
        service.filter_elements(pctx, action="nope")


def test_route_found_enriched(pctx):
    r = service.route(pctx, "act_cs_view_dashboard", "act_cs_create_credential")
    assert r["found"] is True
    assert r["crosses_app"] is False
    assert r["risk_max"] in pctx.pack.config.risk.levels
    assert "console" in r["requires_auth"]


def test_route_not_found(pctx):
    r = service.route(pctx, "act_cs_view_dashboard", "act_pt_submit_withdrawal")
    assert r["found"] is False
    assert "reason" in r


def test_uses_delegates(pctx):
    assert service.uses(pctx, "cs_input_email")["kind"] == "element"


# --- compile / validate / verify ------------------------------------------


def test_compile_script_via_flow_path_actions(pctx):
    by_flow = service.compile_script(pctx, flow="create_project_with_credential")
    assert by_flow.name == "create_project_with_credential"
    by_path = service.compile_script(pctx, src="act_cs_open_projects", dst="act_cs_create_project")
    assert by_path.steps
    by_actions = service.compile_script(pctx, actions=["act_cs_open_projects"])
    assert by_actions.name == "adhoc"


def test_compile_script_requires_a_target(pctx):
    with pytest.raises(ValueError):
        service.compile_script(pctx)


def test_validate_pack_returns_report(pctx):
    report = service.validate_pack(pctx)
    assert report.ok
    assert report.errors == 0


def test_verify_delegates_to_domain(pctx):
    probe = service.verify(pctx, flow="create_project_with_credential")
    assert probe["read_only"] is True


def test_list_capabilities_with_and_without_check(pctx):
    plain = service.list_capabilities(pctx)
    assert {c["key"] for c in plain} == {"totp", "storage_state"}
    assert all(c["error"] is None for c in plain)  # error omitted when not checking
    checked = service.list_capabilities(pctx, check=True)
    assert all(c["error"] is None for c in checked)


def test_import_markdown_roundtrip(tmp_path):
    md = tmp_path / "map.md"
    md.write_text("act_zz_go uses zz_btn_go.")
    out = tmp_path / "pack"
    result = service.import_markdown(md, out)
    assert result["structured"] is False
    assert "zz" in result["apps"]
    assert result["written"]
