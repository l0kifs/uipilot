"""Renderer coverage: JSON / steps / pw-test / POM output shapes.

The demo flows only exercise fill/click/wait_for/capture ops, so we also build a
synthetic :class:`CompiledScript` here to drive every ``op`` and selector
strategy branch through the pw-test and steps renderers.
"""

from __future__ import annotations

import json

from uipilot.domain.compiler import CompiledScript, CompiledStep, compile_flow
from uipilot.domain.model import Selector
from uipilot.presentation import renderers


def _step(op, **kw):
    return CompiledStep(n=kw.pop("n", 1), op=op, **kw)


def _synthetic_script():
    role = Selector(strategy="role", role="button", name="Go").as_dict()
    label = Selector(strategy="label", label="Password").as_dict()
    return CompiledScript(
        name="synthetic",
        app="demo",
        requires_auth=["demo"],
        risk_max="low",
        crosses_app=False,
        params={"x": "1"},
        params_required=["x"],
        preconditions=[{"kind": "auth", "flow": "sign_in"},
                       {"kind": "api_action", "id": "api_seed"}],
        steps=[
            _step("navigate", value="https://example.test/go"),
            _step("snapshot"),
            _step("click", selector=role),
            _step("fill", selector=label, value="secret"),
            _step("select", selector=role, value="opt-a"),
            _step("press", value="Enter"),
            _step("wait_for", mcp={"tool": "browser_wait_for", "args": {"text": "Done"}}),
            _step("wait_for", mcp={"tool": "browser_wait_for", "args": {}}),
            _step("expect", selector=role),
            _step("capture", capture="proj.id", from_="url"),
            _step("upload", selector=role, value="/tmp/f.png"),
            _step("fill_form", note="batched 2 field fills"),
            _step("bogus_op"),
        ],
        crosschecks=[{"id": "api_assert", "call": "clients.op:get"}],
    )


# --- JSON / steps ----------------------------------------------------------


def test_to_json_omits_mcp(pack, ctx):
    s = compile_flow(pack, ctx, "create_project_with_credential")
    data = json.loads(renderers.to_json(s))
    assert "mcp" not in data["steps"][0]


def test_to_steps_compacts_rows():
    data = json.loads(renderers.to_steps(_synthetic_script()))
    assert data["flow"] == "synthetic"
    ops = {r["op"] for r in data["steps"]}
    assert {"navigate", "click", "capture"} <= ops
    cap = next(r for r in data["steps"] if r["op"] == "capture")
    assert cap["capture"] == "proj.id"
    sel = next(r for r in data["steps"] if r["op"] == "click")
    assert "selector" in sel


# --- pw-test: every op + precondition/crosscheck comments ------------------


def test_to_pw_test_covers_all_ops():
    spec = renderers.to_pw_test(_synthetic_script())
    assert "page.goto('https://example.test/go')" in spec
    assert ".click();" in spec
    assert ".fill('secret')" in spec
    assert ".selectOption('opt-a')" in spec
    assert "page.keyboard.press('Enter')" in spec
    assert "getByText('Done')" in spec          # wait_for with text
    assert "// wait_for" in spec                 # wait_for without text
    assert "toBeVisible()" in spec               # expect
    assert "// capture proj.id from url" in spec
    assert "setInputFiles('/tmp/f.png')" in spec
    assert "// fill_form" in spec
    assert "// bogus_op" in spec                 # default branch
    assert "precondition: auth sign_in" in spec
    assert "crosscheck: api_assert" in spec


def test_to_pw_test_from_real_flow(pack, ctx):
    s = compile_flow(pack, ctx, "create_project_with_credential")
    spec = renderers.to_pw_test(s)
    assert "getByRole('button', { name: 'Sign in' })" in spec


# --- human preview ---------------------------------------------------------


def test_to_human_covers_all_ops():
    s = _synthetic_script()
    s.param_capabilities = {"x": "totp"}
    s.teardown = [{"id": "api_del", "call": "factories.x:delete"}]
    text = renderers.to_human(s)
    assert "Flow: synthetic  (app: demo)" in text
    assert "risk: low" in text
    assert "requires auth: demo" in text
    # a required param a capability can mint is annotated, not asked of a human
    assert "minted by capability 'totp'" in text
    assert "sign in — reuse session" in text
    assert "provision via API" in text
    # every op renders a plain-English line
    assert "go to https://example.test/go" in text
    assert "take a page snapshot" in text
    assert 'select "opt-a" in' in text
    assert "press Enter" in text
    assert "wait for Done" in text
    assert "wait for the page to settle" in text  # wait_for with no target
    assert "capture proj.id from url" in text
    assert "upload /tmp/f.png" in text
    assert "fill several fields" not in text  # fill_form carries a note
    assert "batched 2 field fills" in text
    assert "bogus_op" in text                 # default branch
    assert "Cross-checks" in text and "Teardown" in text


def test_to_human_required_param_without_capability():
    text = renderers.to_human(_synthetic_script())
    assert "required — you must supply" in text


def test_to_human_refused_short_circuits():
    s = _synthetic_script()
    s.refused = "path carries gated risk ['money-moving']"
    text = renderers.to_human(s)
    assert "⚠ REFUSED" in text
    assert "Steps:" not in text  # nothing executable is shown


# --- selector-dict inference + python locator ------------------------------


def test_selector_from_dict_infers_strategy():
    assert renderers._selector_from_dict({"role": "button"}).strategy == "role"
    assert renderers._selector_from_dict({"css": ".x"}).strategy == "css"
    assert renderers._selector_from_dict({"text": "Hi"}).strategy == "text"
    assert renderers._selector_from_dict({"label": "L"}).strategy == "label"
    assert renderers._selector_from_dict({"testid": "t"}).strategy == "testid"
    assert renderers._selector_from_dict({}).strategy == "css"  # fallback


def test_py_locator_all_strategies():
    assert renderers._py_locator(
        Selector(strategy="role", role="button", name="Go", exact=True)
    ) == 'get_by_role("button", name="Go", exact=True)'
    assert renderers._py_locator(Selector(strategy="label", label="Pw")) == 'get_by_label("Pw")'
    assert renderers._py_locator(Selector(strategy="text", text="Hi")) == 'get_by_text("Hi")'
    assert renderers._py_locator(Selector(strategy="testid", testid="t")) == 'get_by_test_id("t")'
    assert renderers._py_locator(Selector(strategy="css", css=".x")) == 'locator(".x")'
    scoped = renderers._py_locator(Selector(strategy="role", role="button",
                                            name="Create", scope="dialog"))
    assert scoped.startswith('get_by_role("dialog").')


# --- POM -------------------------------------------------------------------


def test_render_pom_all_apps_and_scoped(pack):
    full = renderers.render_pw_pom(pack)
    assert "class ConsolePage" in full and "class PortalPage" in full
    scoped = renderers.render_pw_pom(pack, "portal")
    assert "class PortalPage" in scoped and "class ConsolePage" not in scoped
    # unknown app id yields no page class body but does not raise
    assert "Page:" not in renderers.render_pw_pom(pack, "ghost")
