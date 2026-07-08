"""Focused domain-layer tests: usage index, model helpers, templating, graph.

Complements the flow/compile/validate suites by exercising the small pure
helpers and their edge branches directly.
"""

from __future__ import annotations

from uipilot.domain import usage
from uipilot.domain.graph import find_path, reachable_actions
from uipilot.domain.model import (
    Action,
    App,
    Config,
    Param,
    PathStep,
    RiskTaxonomy,
    Selector,
    Token,
)
from uipilot.domain.templating import RuntimeContext, iter_template_refs, resolve_template

# ---------------------------------------------------------------------------
# usage.uses — every ref kind
# ---------------------------------------------------------------------------


def test_uses_element(pack):
    out = usage.uses(pack, "cs_input_email")
    assert out["kind"] == "element"
    assert any(a["id"] == "act_cs_sign_in_submit" for a in out["used_by_actions"])
    assert "create_project_with_credential" in out["used_by_flows"] or out["used_by_flows"]
    assert "action(s)" in out["impact"]


def test_uses_action(pack):
    out = usage.uses(pack, "act_cs_create_project")
    assert out["kind"] == "action"
    assert out["used_by_flows"]
    assert "prev" in out["neighbours"] and "next" in out["neighbours"]
    assert "act_cs_open_projects" in out["referenced_by_edges"]


def test_uses_flow(pack):
    out = usage.uses(pack, "console_sign_in")
    assert out["kind"] == "flow"
    # embedded via `use:` in create_project_with_credential
    assert "create_project_with_credential" in out["used_by_flows"]


def test_uses_unknown(pack):
    out = usage.uses(pack, "nope")
    assert out["kind"] == "unknown"
    assert "error" in out


# ---------------------------------------------------------------------------
# Selector rendering — all strategies / describe / as_dict
# ---------------------------------------------------------------------------


def test_selector_to_locator_all_strategies():
    assert Selector(strategy="testid", testid="t").to_locator() == "getByTestId('t')"
    assert Selector(strategy="css", css=".x").to_locator() == "locator('.x')"
    assert Selector(strategy="label", label="Password").to_locator() == "getByLabel('Password')"
    assert Selector(strategy="text", text="Hi").to_locator() == "getByText('Hi')"
    exact = Selector(strategy="role", role="button", name="Go", exact=True)
    assert exact.to_locator() == "getByRole('button', { name: 'Go', exact: true })"


def test_selector_describe_variants():
    s = Selector(strategy="role", role="button", name="Create", scope="dialog")
    # type appended when the label doesn't already mention it
    assert s.describe("button") == "dialog Create button"
    # type omitted when the label already contains it
    named = Selector(strategy="role", role="button", name="Submit button", scope="dialog")
    assert named.describe("button") == "dialog Submit button"
    bare = Selector(strategy="css", css=".x")
    assert bare.describe("button") == ".x button"
    empty = Selector(strategy="css")
    assert empty.describe() == "element"
    assert empty.describe("input") == "input"


def test_selector_as_dict_and_signature():
    s = Selector(strategy="role", role="button", name="Go", exact=True, scope="dialog")
    d = s.as_dict()
    assert d["exact"] is True and d["scope"] == "dialog"
    assert isinstance(s.signature(), tuple)
    assert Selector(strategy="css").as_dict() == {"strategy": "css"}


# ---------------------------------------------------------------------------
# Param / Action / PathStep / RiskTaxonomy / Config
# ---------------------------------------------------------------------------


def test_param_is_secret():
    assert Param("pw", type="secret").is_secret
    assert not Param("name").is_secret


def test_action_param_lookup_and_transport():
    a = Action(id="a", app="x", transport="api", params=[Param("k")])
    assert a.is_api and not a.is_ui
    assert a.param("k").key == "k"
    assert a.param("missing") is None


def test_pathstep_ref_and_subflow():
    assert PathStep(action="a").ref == "a"
    assert PathStep(use="f").ref == "f" and PathStep(use="f").is_subflow
    assert PathStep().ref == "?" and not PathStep().is_subflow


def test_risk_taxonomy_rank_and_max():
    rt = RiskTaxonomy(levels=["low", "high"], gated=["high"])
    assert rt.rank("low") == 0 and rt.rank("unknown") == -1
    assert rt.max(["low", "high"]) == "high"
    assert rt.max(["unknown"]) == "unknown"  # nothing in taxonomy → first
    assert rt.max([]) is None


def test_config_and_pack_lookups(pack):
    assert pack.app("console").id == "console"
    assert pack.app("ghost") is None
    assert pack.action("act_cs_create_project") is not None
    assert pack.element("cs_input_email") is not None
    assert pack.flow("console_sign_in") is not None
    assert {a.id for a in pack.actions_for_app("portal")}
    assert pack.ui_actions() and pack.api_actions()


# ---------------------------------------------------------------------------
# templating
# ---------------------------------------------------------------------------


def test_runtime_base_url_env_and_default():
    app_env = App(id="a", id_prefix="a", base_url_env="A_URL", base_url_default="http://d")
    cfg = Config(pack="p", apps=[])
    with_env = RuntimeContext(cfg, env={"A_URL": "http://env"})
    assert with_env.base_url(app_env) == "http://env"
    without = RuntimeContext(cfg, env={})
    assert without.base_url(app_env) == "http://d"
    no_default = App(id="a", id_prefix="a")
    assert without.base_url(no_default) == ""


def test_runtime_token_counter_and_env_and_unknown():
    cfg = Config(
        pack="p",
        apps=[],
        tokens={
            "seq": Token("seq", "counter"),
            "prefix": Token("prefix", "env", name="P", default="fallback"),
            "weird": Token("weird", "somethingelse", default="dv"),
        },
    )
    ctx = RuntimeContext(cfg, env={})
    assert ctx.token("prefix") == "fallback"  # env missing → default
    assert ctx.token("seq") == "1"  # counter start
    assert ctx.token("seq") == "1"  # cached, stable in a run
    assert ctx.token("weird") == "dv"  # non-env/counter → default
    assert ctx.token("unknown") is None  # absent token


def test_iter_template_refs_and_resolve():
    assert iter_template_refs(None) == []
    assert iter_template_refs("{{a}}-{{b}}") == ["a", "b"]
    out, unresolved = resolve_template(None, {})
    assert out is None and unresolved == []


# ---------------------------------------------------------------------------
# graph edges
# ---------------------------------------------------------------------------


def test_find_path_max_depth_cuts_off(pack):
    r = find_path(pack, "act_cs_view_dashboard", "act_cs_create_credential", max_depth=1)
    assert not r.found


def test_find_path_unknown_target(pack):
    r = find_path(pack, "act_cs_view_dashboard", "ghost")
    assert not r.found and "target" in (r.reason or "")


def test_reachability_includes_entry_flow_roots(pack):
    # console's auth entry flow seeds reachability; every UI action is reached
    reached = reachable_actions(pack)
    assert "act_cs_sign_in_submit" in reached
