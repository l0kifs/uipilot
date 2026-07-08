"""Emit a read-only probe script to detect live drift against the running app.

``validate`` answers *"is the map self-consistent?"*; ``verify`` answers *"does
the map still match the running UI?"*. It emits a **read-only** probe (navigate
+ snapshot + assert-each-element-resolves; no clicks that mutate state) that the
agent runs via Playwright MCP. Any element that fails to resolve, or route that
won't load, is drift.

``--drive`` walks a full flow (for pages only reachable by clicking through) but
**refuses ``risk.gated`` steps** unless explicitly opted in — drift-checking a
money-moving flow must not move money. The engine still executes nothing.
"""

from __future__ import annotations

from typing import Optional

from uipilot.domain.compiler import compile_flow
from uipilot.domain.flows import expand_invocations
from uipilot.domain.model import Action, Pack
from uipilot.domain.templating import RuntimeContext


def _route_groups(pack: Pack, actions: list[Action]) -> list[tuple[Optional[str], list[str]]]:
    """Group each action's declared elements under its route, in order."""
    groups: list[tuple[Optional[str], list[str]]] = []
    for action in actions:
        if not action.is_ui:
            continue
        elems = [e for e in action.elements if e in pack.elements]
        groups.append((action.route, elems))
    return groups


def _probe_steps(
    pack: Pack, ctx: RuntimeContext, groups: list[tuple[Optional[str], list[str]]], app_id: str
) -> list[dict]:
    app = pack.app(app_id)
    base_url = ctx.base_url(app) if app else ""
    steps: list[dict] = []
    n = 0
    current_route = object()  # sentinel != None
    for route, elems in groups:
        if route is not None and route != current_route:
            url = (base_url.rstrip("/") + route) if base_url else "{{base_url}}" + route
            n += 1
            steps.append(
                {
                    "n": n,
                    "op": "navigate",
                    "mcp": {"tool": "browser_navigate", "args": {"url": url}},
                }
            )
            n += 1
            steps.append(
                {"n": n, "op": "snapshot", "mcp": {"tool": "browser_snapshot", "args": {}}}
            )
            current_route = route
        for eid in elems:
            el = pack.element(eid)
            if el is None:
                continue
            n += 1
            steps.append(
                {
                    "n": n,
                    "op": "expect",
                    "element": eid,
                    "selector": el.selector.as_dict(),
                    "assert": "element resolves in latest snapshot",
                    "mcp": {"tool": "browser_snapshot", "args": {}},
                }
            )
    return steps


def verify_probe(
    pack: Pack,
    ctx: RuntimeContext,
    *,
    flow: Optional[str] = None,
    app: Optional[str] = None,
    action: Optional[str] = None,
    drive: bool = False,
    allow_gated: bool = False,
) -> dict:
    """Build a read-only probe (or, with ``drive``, a gated flow walk)."""
    if flow:
        flow_obj = pack.flow(flow)
        if flow_obj is None:
            raise KeyError(f"no flow named '{flow}'")
        if drive:
            return _drive(pack, ctx, flow, allow_gated)
        # static probe: assert every element on every UI action in the flow
        action_ids = [inv.action_id for inv in expand_invocations(pack, flow)]
        actions = [act for a in action_ids if (act := pack.action(a)) is not None]
        app_id = flow_obj.app or (actions[0].app if actions else "")
        groups = _route_groups(pack, actions)
        return {
            "mode": "probe",
            "scope": {"flow": flow},
            "read_only": True,
            "app": app_id,
            "steps": _probe_steps(pack, ctx, groups, app_id),
        }
    if action:
        act = pack.action(action)
        if act is None:
            raise KeyError(f"no action named '{action}'")
        groups = _route_groups(pack, [act])
        return {
            "mode": "probe",
            "scope": {"action": action},
            "read_only": True,
            "app": act.app,
            "steps": _probe_steps(pack, ctx, groups, act.app),
        }
    if app:
        if app not in pack.apps:
            raise KeyError(f"no app named '{app}'")
        actions = [a for a in pack.actions_for_app(app) if a.is_ui]
        actions.sort(key=lambda a: (a.route or "", a.id))
        groups = _route_groups(pack, actions)
        return {
            "mode": "probe",
            "scope": {"app": app},
            "read_only": True,
            "app": app,
            "steps": _probe_steps(pack, ctx, groups, app),
        }
    raise ValueError("verify needs one of --flow, --app, or --action")


def _drive(pack: Pack, ctx: RuntimeContext, flow: str, allow_gated: bool) -> dict:
    """Walk the full flow, but refuse gated steps unless explicitly allowed."""
    script = compile_flow(pack, ctx, flow)
    gated = set(pack.config.risk.gated)
    refused: list[str] = []
    kept_steps = []
    for step in script.steps:
        act = pack.action(step.action) if step.action else None
        if act and act.risk in gated and not allow_gated:
            refused.append(f"{step.n}:{step.action} ({act.risk})")
            continue
        kept_steps.append(step.as_dict(with_mcp=True))
    return {
        "mode": "drive",
        "scope": {"flow": flow},
        "read_only": not any(
            act.risk in gated
            for s in script.steps
            if s.action and (act := pack.action(s.action)) is not None
        ),
        "app": script.app,
        "refused_gated": refused,
        "note": (
            "gated steps refused; pass --allow-gated to include them"
            if refused and not allow_gated
            else None
        ),
        "steps": kept_steps,
    }
