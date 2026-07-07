"""Compile action recipes into a resolved flow script.

The compiler concatenates each action's ``steps`` recipe along a path, then:

* inlines subflows (``use:``), applying per-invocation aliases/params;
* routes API ``setup`` actions into ``preconditions`` and ``crosscheck`` actions
  into trailing asserts (they are never navigation nodes);
* prepends the auth precondition (unless ``skip_auth``);
* inserts a ``snapshot`` **only** where the DOM changed (start, post-navigate,
  post-``wait_for``) — the ref-cost optimisation from design §6;
* dedups redundant navigations between adjacent same-route actions;
* substitutes params/tokens/base-url and threads captures as ``{{captured.*}}``;
* computes ``risk_max``/``crosses_app``/``requires_auth`` and gates on
  ``refuse_destructive``.

The engine executes nothing: the result is structured data an agent runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from uipilot.domain.flows import Invocation, expand_invocations
from uipilot.domain.graph import find_path
from uipilot.domain.model import INTERACTING_OPS, Action, Pack
from uipilot.domain.templating import RuntimeContext, resolve_template

# ---------------------------------------------------------------------------
# Output shapes
# ---------------------------------------------------------------------------


@dataclass
class CompiledStep:
    n: int
    op: str
    action: Optional[str] = None
    element: Optional[str] = None
    selector: Optional[dict] = None
    value: Optional[str] = None
    capture: Optional[str] = None
    from_: Optional[str] = None
    pattern: Optional[str] = None
    optional: bool = False
    mcp: Optional[dict] = None
    note: Optional[str] = None

    def as_dict(self, *, with_mcp: bool = True) -> dict:
        out: dict = {"n": self.n, "op": self.op}
        for key in ("action", "element", "selector", "value", "capture",
                    "from_", "pattern", "note"):
            val = getattr(self, key)
            if val is not None:
                out[key.rstrip("_") if key == "from_" else key] = val
        if self.optional:
            out["optional"] = True
        if with_mcp and self.mcp is not None:
            out["mcp"] = self.mcp
        return out


@dataclass
class CompiledScript:
    name: str
    app: str
    requires_auth: list[str]
    risk_max: Optional[str]
    crosses_app: bool
    params: dict
    params_required: list[str]
    preconditions: list[dict]
    steps: list[CompiledStep]
    crosschecks: list[dict] = field(default_factory=list)
    refused: Optional[str] = None
    teardown: Optional[dict] = None

    def as_dict(self, *, with_mcp: bool = True) -> dict:
        out: dict = {
            "flow": self.name,
            "app": self.app,
            "requires_auth": self.requires_auth,
            "risk_max": self.risk_max,
            "crosses_app": self.crosses_app,
        }
        if self.refused:
            out["refused"] = self.refused
        out["params"] = self.params
        out["params_required"] = self.params_required
        out["preconditions"] = self.preconditions
        out["steps"] = [s.as_dict(with_mcp=with_mcp) for s in self.steps]
        if self.crosschecks:
            out["crosschecks"] = self.crosschecks
        if self.teardown:
            out["teardown"] = self.teardown
        return out


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


class _Compiler:
    def __init__(self, pack: Pack, ctx: RuntimeContext,
                 overrides: Optional[dict] = None,
                 skip_auth: bool = False, batch: bool = False,
                 refuse_destructive: bool = False) -> None:
        self.pack = pack
        self.ctx = ctx
        self.overrides = overrides or {}
        self.skip_auth = skip_auth
        self.batch = batch
        self.refuse_destructive = refuse_destructive
        self.params_echo: dict[str, str] = {}
        self.params_required: list[str] = []
        self._produced_captures: set[str] = set()

    # -- param resolution ---------------------------------------------------

    def _resolve_param(self, param, inv_params: dict, flow_defaults: dict):
        """Return (echo_value, step_value, missing) for one param."""
        user_override = None
        for src in (inv_params, self.overrides):
            if param.key in src and src[param.key] is not None:
                user_override = str(src[param.key])
                break
        raw = user_override
        if raw is None and param.key in flow_defaults and flow_defaults[param.key] is not None:
            raw = flow_defaults[param.key]
        if raw is None:
            raw = param.default

        if raw is None:
            placeholder = f"{{{{{param.key}}}}}"
            missing = param.required
            return placeholder, placeholder, missing

        resolved, unresolved = resolve_template(raw, {}, self.ctx)
        missing = param.required and bool(unresolved)

        if param.is_secret:
            placeholder = f"{{{{{param.key}}}}}"
            # Secret only materialises in the consuming step, and only when the
            # caller actually supplied it — never echoed, never from a default.
            step_value = resolved if (user_override is not None and not unresolved) else placeholder
            missing = param.required and user_override is None
            return placeholder, step_value, missing
        return resolved, resolved, missing

    def _build_param_map(self, action: Action, inv_params: dict,
                         flow_defaults: dict) -> dict:
        pmap: dict[str, str] = {}
        for param in action.params:
            echo, step_value, missing = self._resolve_param(param, inv_params, flow_defaults)
            pmap[param.key] = step_value
            # Record echo/required once (first occurrence wins for the header).
            if param.key not in self.params_echo:
                self.params_echo[param.key] = echo
                if missing and param.key not in self.params_required:
                    self.params_required.append(param.key)
        return pmap

    def _register_flow_params(self, flow_params, flow_defaults):
        for param in flow_params:
            echo, _step, missing = self._resolve_param(param, {}, flow_defaults)
            if param.key not in self.params_echo:
                self.params_echo[param.key] = echo
                if missing and param.key not in self.params_required:
                    self.params_required.append(param.key)

    # -- step emission ------------------------------------------------------

    def _mcp_for(self, op: str, *, url=None, desc=None, value=None,
                 wait_for=None, key=None, args=None) -> Optional[dict]:
        args = args or {}
        if op == "navigate":
            return {"tool": "browser_navigate", "args": {"url": url}}
        if op == "snapshot":
            return {"tool": "browser_snapshot", "args": {}}
        if op == "click":
            return {"tool": "browser_click", "args": {"element": desc, "ref": "@snapshot"}}
        if op in ("fill", "type"):
            return {"tool": "browser_type",
                    "args": {"element": desc, "ref": "@snapshot", "text": value}}
        if op == "select":
            values = args.get("values") or ([value] if value else [])
            return {"tool": "browser_select_option",
                    "args": {"element": desc, "ref": "@snapshot", "values": values}}
        if op == "press":
            return {"tool": "browser_press_key",
                    "args": {"key": args.get("key") or value or key}}
        if op == "wait_for":
            return {"tool": "browser_wait_for", "args": wait_for or {}}
        if op == "expect":
            return {"tool": "browser_snapshot", "args": {}}
        if op == "upload":
            paths = args.get("paths") or ([value] if value else [])
            return {"tool": "browser_file_upload", "args": {"paths": paths}}
        if op == "capture":
            # url captures read the address bar; element/response use evaluate.
            return None
        return None

    # -- main ---------------------------------------------------------------

    def compile(self, invocations: list[Invocation], *, name: str,
                flow_params=None, flow_defaults=None,
                primary_app: Optional[str] = None) -> CompiledScript:
        flow_params = flow_params or []
        flow_defaults = flow_defaults or {p.key: p.default for p in flow_params}
        self._register_flow_params(flow_params, flow_defaults)

        ui_invs: list[Invocation] = []
        setup_pre: list[dict] = []
        crosschecks: list[dict] = []
        risks: list[str] = []
        apps_seen: list[str] = []

        for inv in invocations:
            action = self.pack.action(inv.action_id)
            if action is None:
                continue
            risks.append(action.risk)
            pmap = self._build_param_map(action, inv.params, flow_defaults)
            if action.is_api:
                role = inv.role or action.role or "setup"
                entry = {
                    "kind": "api_action",
                    "id": action.id,
                    "call": action.call,
                    "args": self._resolve_args(action, pmap),
                    "captures": [c.key for c in action.captures],
                    "risk": action.risk,
                    "run_by": "agent",
                }
                for cap in action.captures:
                    self._produced_captures.add(cap.key)
                if role == "crosscheck":
                    crosschecks.append(entry)
                else:
                    setup_pre.append(entry)
            else:
                if action.app not in apps_seen:
                    apps_seen.append(action.app)
                ui_invs.append(inv)

        primary_app = primary_app or (apps_seen[0] if apps_seen else
                                      (self.pack.config.apps[0] if self.pack.config.apps else ""))

        # Refuse-destructive gate.
        refused = None
        gated = set(self.pack.config.risk.gated)
        if self.refuse_destructive:
            offending = sorted({r for r in risks if r in gated})
            if offending:
                refused = (f"path carries gated risk {offending}; "
                           "re-run without --refuse-destructive to emit")

        # Preconditions: API setups first, then auth.
        preconditions: list[dict] = list(setup_pre)
        requires_auth: list[str] = []
        if not self.skip_auth:
            auth_pre, requires_auth = self._auth_preconditions(ui_invs, primary_app)
            preconditions += auth_pre

        steps: list[CompiledStep] = []
        if refused is None:
            steps = self._emit_ui_steps(ui_invs, flow_defaults)
            if self.batch:
                steps = self._collapse_fills(steps)
            for i, step in enumerate(steps, start=1):
                step.n = i

        risk_max = self.pack.config.risk.max(risks) if risks else None
        crosses_app = len(apps_seen) > 1

        return CompiledScript(
            name=name,
            app=primary_app,
            requires_auth=requires_auth,
            risk_max=risk_max,
            crosses_app=crosses_app,
            params=dict(self.params_echo),
            params_required=list(self.params_required),
            preconditions=preconditions,
            steps=steps,
            crosschecks=crosschecks,
            refused=refused,
        )

    def _resolve_args(self, action: Action, pmap: dict) -> dict:
        args = {}
        for param in action.params:
            args[param.key] = pmap.get(param.key)
        return args

    def _auth_preconditions(self, ui_invs, primary_app):
        app = self.pack.app(primary_app)
        if not app or not app.auth or not app.auth.entry_flow:
            return [], []
        entry_flow = app.auth.entry_flow
        # Skip if the flow already runs the auth subflow explicitly.
        entry = self.pack.flow(entry_flow)
        entry_first = None
        if entry and entry.path and entry.path[0].action:
            entry_first = entry.path[0].action
        present = {inv.action_id for inv in ui_invs}
        if entry_first and entry_first in present:
            return [], [primary_app]
        key = app.auth.storage_state_key or primary_app
        pre = {
            "kind": "auth",
            "flow": entry_flow,
            "storage_state_key": key,
            "hint": (f"reuse Playwright storageState '{key}' if present and fresh; "
                     "else run the sign-in subflow and re-save state"),
            "run_by": "agent",
        }
        return [pre], [primary_app]

    def _emit_ui_steps(self, ui_invs, flow_defaults) -> list[CompiledStep]:
        steps: list[CompiledStep] = []
        current_route: Optional[str] = None
        needs_snapshot = True

        def emit_snapshot():
            steps.append(CompiledStep(n=0, op="snapshot",
                                      mcp=self._mcp_for("snapshot")))

        for inv in ui_invs:
            action = self.pack.action(inv.action_id)
            if action is None:
                continue
            app = self.pack.app(action.app)
            base_url = self.ctx.base_url(app) if app else ""
            pmap = self._build_param_map(action, inv.params, flow_defaults)

            # Synthesised navigation (deduped against the current route).
            if action.route and action.route != current_route:
                url = (base_url.rstrip("/") + action.route) if base_url else \
                    "{{base_url}}" + action.route
                steps.append(CompiledStep(n=0, op="navigate", action=action.id,
                                          value=url, mcp=self._mcp_for("navigate", url=url)))
                current_route = action.route
                needs_snapshot = True

            for step in action.steps:
                if step.op == "navigate":
                    current_route = None  # explicit navigate; recompute below
                if step.op in INTERACTING_OPS and needs_snapshot:
                    emit_snapshot()
                    needs_snapshot = False

                cstep = self._compile_step(action, step, pmap, base_url)
                steps.append(cstep)

                if step.op in ("navigate",):
                    needs_snapshot = True
                if step.op == "wait_for":
                    needs_snapshot = True

            # Action-level captures become explicit capture steps.
            for cap in action.captures:
                self._produced_captures.add(cap.key)
                key = f"{inv.alias}.{cap.key}" if inv.alias else cap.key
                steps.append(CompiledStep(
                    n=0, op="capture", action=action.id,
                    capture=key, from_=cap.from_, pattern=cap.pattern,
                    mcp=self._mcp_for("capture", key=key),
                ))

        return steps

    def _compile_step(self, action: Action, step, pmap: dict, base_url: str) -> CompiledStep:
        element = self.pack.element(step.element) if step.element else None
        selector = element.selector.as_dict() if element else None
        if step.scope and selector is not None:
            selector.setdefault("scope", step.scope)
        desc = element.selector.describe(element.type) if element else (step.element or step.op)

        values = {"base_url": base_url, **pmap}
        value, unresolved = resolve_template(step.value, values, self.ctx)
        for ref in unresolved:
            if "." not in ref and ref not in self.params_required:
                self.params_required.append(ref)

        wait_for = None
        if step.wait_for:
            wait_for = {}
            for k, v in step.wait_for.items():
                rv, _ = resolve_template(v, values, self.ctx) if isinstance(v, str) else (v, [])
                wait_for[k] = rv
        elif step.op == "wait_for" and element is not None:
            # Derive a text wait from the awaited element's accessible name.
            text = element.selector.name or element.selector.text
            if text:
                wait_for = {"text": text}

        note = None
        if step.op == "expect":
            note = f"assert element resolves: {desc}"

        mcp = self._mcp_for(step.op, desc=desc, value=value, wait_for=wait_for,
                            args=step.args)
        return CompiledStep(
            n=0, op=step.op, action=action.id, element=step.element,
            selector=selector, value=value, optional=step.optional,
            mcp=mcp, note=note,
        )

    def _collapse_fills(self, steps: list[CompiledStep]) -> list[CompiledStep]:
        """Merge runs of adjacent fill/type steps into one browser_fill_form."""
        out: list[CompiledStep] = []
        run: list[CompiledStep] = []

        def flush():
            if not run:
                return
            if len(run) == 1:
                out.append(run[0])
            else:
                fields = [{
                    "name": s.selector.get("name") if s.selector else s.element,
                    "type": "textbox",
                    "ref": "@snapshot",
                    "value": s.value,
                } for s in run]
                out.append(CompiledStep(
                    n=0, op="fill_form", action=run[0].action,
                    mcp={"tool": "browser_fill_form", "args": {"fields": fields}},
                    note=f"batched {len(run)} field fills",
                ))
            run.clear()

        for step in steps:
            if step.op in ("fill", "type"):
                run.append(step)
            else:
                flush()
                out.append(step)
        flush()
        return out


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def compile_flow(pack: Pack, ctx: RuntimeContext, flow_id: str, **kw) -> CompiledScript:
    flow = pack.flow(flow_id)
    if flow is None:
        raise KeyError(f"no flow named '{flow_id}'")
    invs = expand_invocations(pack, flow_id)
    flow_defaults = {p.key: p.default for p in flow.params}
    comp = _Compiler(pack, ctx, **kw)
    return comp.compile(invs, name=flow_id, flow_params=flow.params,
                        flow_defaults=flow_defaults, primary_app=flow.app)


def compile_actions(pack: Pack, ctx: RuntimeContext, action_ids: list[str],
                    *, name: str = "adhoc", **kw) -> CompiledScript:
    invs = [Invocation(aid, None, {}, None) for aid in action_ids]
    comp = _Compiler(pack, ctx, **kw)
    return comp.compile(invs, name=name)


def compile_path(pack: Pack, ctx: RuntimeContext, src: str, dst: str,
                 max_depth: int = 25, **kw) -> CompiledScript:
    result = find_path(pack, src, dst, max_depth=max_depth)
    if not result.found:
        raise KeyError(result.reason or "no path")
    return compile_actions(pack, ctx, result.path, name=f"{src}->{dst}", **kw)
