"""Renderers: turn a :class:`CompiledScript` or the model into an output format.

Formats:

* ``json``          — the fully resolved flow object (no MCP wrapper).
* ``playwright-mcp`` — the same, each step annotated with its exact MCP tool+args.
* ``steps``         — a compact ``op``/``selector``/``value`` list for other executors.
* ``pw-test``       — a real ``@playwright/test`` spec.
* ``pw-pom``        — Python Page Object Model classes generated from the YAML
                      (build artifacts; never hand-edited — design DEC-UICLI-6).
"""

from __future__ import annotations

import json
from typing import Optional

from uipilot.domain.compiler import CompiledScript
from uipilot.domain.model import Element, Pack, Selector

# ---------------------------------------------------------------------------
# Script renderers
# ---------------------------------------------------------------------------


def to_json(script: CompiledScript) -> str:
    return json.dumps(script.as_dict(with_mcp=False), indent=2)


def to_playwright_mcp(script: CompiledScript) -> str:
    return json.dumps(script.as_dict(with_mcp=True), indent=2)


def to_human(script: CompiledScript) -> str:
    """A plain-English preview of a compiled flow, for a human to review before
    an agent runs it — especially useful before approving a gated (destructive /
    money-moving) flow. Emits no MCP/JSON, just numbered prose."""
    L: list[str] = []
    L.append(f"Flow: {script.name}  (app: {script.app})")
    facts = [f"risk: {script.risk_max or 'none'}"]
    if script.requires_auth:
        facts.append(f"requires auth: {', '.join(script.requires_auth)}")
    if script.crosses_app:
        facts.append("crosses app: yes")
    L.append("  " + " · ".join(facts))

    if script.refused:
        L.append("")
        L.append(f"⚠ REFUSED: {script.refused}")
        return "\n".join(L)

    if script.params:
        L.append("")
        L.append("Params:")
        for key, val in script.params.items():
            note = ""
            if key in script.params_required:
                cap = script.param_capabilities.get(key)
                note = (
                    f"  (required — minted by capability '{cap}')"
                    if cap
                    else "  (required — you must supply)"
                )
            L.append(f"  {key} = {val}{note}")

    if script.preconditions:
        L.append("")
        L.append("Preconditions (run first):")
        for i, pre in enumerate(script.preconditions, 1):
            if pre.get("kind") == "auth":
                L.append(
                    f"  {i}. sign in — reuse session "
                    f"'{pre.get('storage_state_key')}' or run flow '{pre.get('flow')}'"
                )
            else:
                L.append(f"  {i}. provision via API — {pre.get('call')}")

    L.append("")
    L.append("Steps:")
    for step in script.steps:
        L.append(f"  {step.n}. {_human_step(step)}")

    if script.crosschecks:
        L.append("")
        L.append("Cross-checks (assert backend afterwards):")
        for cc in script.crosschecks:
            L.append(f"  - {cc.get('id')} → {cc.get('call')}")

    if script.teardown:
        L.append("")
        L.append("Teardown (cleanup afterwards):")
        for td in script.teardown:
            L.append(f"  - {td.get('id')} → {td.get('call')}")

    return "\n".join(L)


def _human_step(step) -> str:
    args = (step.mcp or {}).get("args", {})
    desc = args.get("element") or step.element or ""
    op = step.op
    if op == "navigate":
        return f"go to {step.value or args.get('url', '')}"
    if op == "snapshot":
        return "take a page snapshot"
    if op == "click":
        return f"click {desc}"
    if op in ("fill", "type"):
        return f'fill {desc} with "{step.value}"'
    if op == "select":
        return f'select "{step.value}" in {desc}'
    if op == "press":
        return f"press {step.value or args.get('key', '')}"
    if op == "wait_for":
        target = args.get("text") or args.get("textGone") or desc or "the page to settle"
        return f"wait for {target}"
    if op == "expect":
        return step.note or f"assert {desc} is present"
    if op == "capture":
        return f"capture {step.capture} from {step.from_}"
    if op == "upload":
        return f"upload {step.value}"
    if op == "fill_form":
        return step.note or "fill several fields"
    return op


def to_steps(script: CompiledScript) -> str:
    rows = []
    for step in script.steps:
        row = {"n": step.n, "op": step.op}
        if step.selector:
            row["selector"] = step.selector
        if step.value is not None:
            row["value"] = step.value
        if step.capture:
            row["capture"] = step.capture
        rows.append(row)
    return json.dumps(
        {
            "flow": script.name,
            "preconditions": script.preconditions,
            "steps": rows,
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# Playwright locator helpers (from a selector dict on a compiled step)
# ---------------------------------------------------------------------------


def _selector_from_dict(raw: dict) -> Selector:
    strategy = raw.get("strategy")
    if not strategy:
        if raw.get("role"):
            strategy = "role"
        elif raw.get("css"):
            strategy = "css"
        elif raw.get("text"):
            strategy = "text"
        elif raw.get("label"):
            strategy = "label"
        elif raw.get("testid"):
            strategy = "testid"
        else:
            strategy = "css"
    return Selector(
        strategy=strategy,
        role=raw.get("role"),
        name=raw.get("name"),
        text=raw.get("text"),
        label=raw.get("label"),
        css=raw.get("css"),
        testid=raw.get("testid"),
        scope=raw.get("scope"),
        exact=raw.get("exact"),
    )


def _py_locator(sel: Selector) -> str:
    def _q(v: str) -> str:
        return '"' + (v or "").replace("\\", "\\\\").replace('"', '\\"') + '"'

    if sel.strategy == "role":
        extra = f", name={_q(sel.name)}" if sel.name else ""
        if sel.exact:
            extra += ", exact=True"
        base = f"get_by_role({_q(sel.role or '')}{extra})"
    elif sel.strategy == "label":
        base = f"get_by_label({_q(sel.label or sel.name or '')})"
    elif sel.strategy == "text":
        base = f"get_by_text({_q(sel.text or sel.name or '')})"
    elif sel.strategy == "testid":
        base = f"get_by_test_id({_q(sel.testid or '')})"
    else:
        base = f"locator({_q(sel.css or '')})"
    if sel.scope:
        return f"get_by_role({_q(sel.scope)}).{base}"
    return base


# ---------------------------------------------------------------------------
# @playwright/test spec
# ---------------------------------------------------------------------------


def to_pw_test(script: CompiledScript) -> str:
    lines = [
        "import { test, expect } from '@playwright/test';",
        "",
        f"// Generated by uipilot from flow '{script.name}'. Do not hand-edit.",
        f"// requires_auth: {', '.join(script.requires_auth) or 'none'}"
        f"  risk_max: {script.risk_max}",
    ]
    for pre in script.preconditions:
        lines.append(
            f"//   precondition: {pre.get('kind')} {pre.get('id') or pre.get('flow') or ''}"
        )
    lines.append("")
    lines.append(f"test({_js(script.name)}, async ({{ page }}) => {{")
    for step in script.steps:
        lines.append("  " + _pw_line(step))
    for cc in script.crosschecks:
        lines.append(f"  // crosscheck: {cc.get('id')} -> {cc.get('call')}")
    lines.append("});")
    lines.append("")
    return "\n".join(lines)


def _js(value: str) -> str:
    return "'" + (value or "").replace("\\", "\\\\").replace("'", "\\'") + "'"


def _pw_line(step) -> str:
    op = step.op
    if op == "navigate":
        return f"await page.goto({_js(step.value or '')});"
    if op == "snapshot":
        return "// snapshot (implicit in @playwright/test)"
    loc = f"page.{_py_to_js(step.selector)}" if step.selector else "page"
    if op == "click":
        return f"await {loc}.click();"
    if op in ("fill", "type"):
        return f"await {loc}.fill({_js(step.value or '')});"
    if op == "select":
        return f"await {loc}.selectOption({_js(step.value or '')});"
    if op == "press":
        return f"await page.keyboard.press({_js(step.value or '')});"
    if op == "wait_for":
        text = (step.mcp or {}).get("args", {}).get("text") if step.mcp else None
        if text:
            return f"await expect(page.getByText({_js(text)})).toBeVisible();"
        return "// wait_for"
    if op == "expect":
        return f"await expect({loc}).toBeVisible();"
    if op == "capture":
        return f"// capture {step.capture} from {step.from_}"
    if op == "upload":
        return f"await {loc}.setInputFiles({_js(step.value or '')});"
    if op == "fill_form":
        return f"// fill_form ({step.note})"
    return f"// {op}"


def _py_to_js(selector_dict: dict) -> str:
    """Render a selector dict to a JS locator (getByRole(...))."""
    return _selector_from_dict(selector_dict).to_locator()


# ---------------------------------------------------------------------------
# Python POM generation
# ---------------------------------------------------------------------------


def render_pw_pom(pack: Pack, app_id: Optional[str] = None) -> str:
    apps = [app_id] if app_id else list(pack.apps)
    out = [
        '"""Generated Page Object Model classes. DO NOT EDIT.',
        "",
        "Regenerated from the uipilot YAML via `uipilot emit --format pw-pom`.",
        "The YAML is the single selector source; hand-editing here is forbidden.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from playwright.sync_api import Page",
        "",
    ]
    for aid in apps:
        app = pack.app(aid)
        if app is None:
            continue
        class_name = _class_name(aid)
        out.append(f"class {class_name}:")
        out.append(f'    """Page object for app \'{aid}\'."""')
        out.append("")
        out.append("    def __init__(self, page: Page) -> None:")
        out.append("        self.page = page")
        out.append("")
        elements = sorted(
            (e for e in pack.elements.values() if e.app == aid),
            key=lambda e: e.id,
        )
        for el in elements:
            method = _element_method(el, app.id_prefix)
            if el.purpose:
                out.append(f"    # {el.purpose}")
            out.append("    @property")
            out.append(f"    def {method}(self):")
            out.append(f"        return self.page.{_py_locator(el.selector)}")
            out.append("")
        out.append("")
    return "\n".join(out)


def _class_name(app_id: str) -> str:
    return "".join(part.capitalize() for part in app_id.replace("-", "_").split("_")) + "Page"


def _element_method(el: Element, id_prefix: str) -> str:
    name = el.id
    for pref in (f"{id_prefix}_", f"{el.app}_"):
        if name.startswith(pref):
            name = name[len(pref) :]
            break
    return name or el.id
