"""Static model linter — the CI guard against map rot.

``validate`` answers *"is the map self-consistent?"* (offline, fast). It cannot
know the app changed — only that the model is internally inconsistent. The
companion live check (``verify``, emitted by :mod:`uipilot.script`) answers
*"does the map still match the running UI?"*.

Findings are returned as structured :class:`Finding`s, never raised, so a single
pass reports every problem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from uipilot.domain.flows import flatten_flow
from uipilot.domain.graph import reachable_actions
from uipilot.domain.model import Action, Pack
from uipilot.domain.templating import iter_template_refs

ERROR = "error"
WARNING = "warning"


@dataclass
class Finding:
    severity: str
    code: str
    ref: str
    message: str

    def as_dict(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "ref": self.ref,
            "message": self.message,
        }


@dataclass
class ValidationReport:
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity == ERROR)

    @property
    def warnings(self) -> int:
        return sum(1 for f in self.findings if f.severity == WARNING)

    @property
    def ok(self) -> bool:
        return self.errors == 0

    def as_dict(self) -> dict:
        return {
            "errors": self.errors,
            "warnings": self.warnings,
            "findings": [f.as_dict() for f in self.findings],
        }


# ---------------------------------------------------------------------------
# Individual lint passes
# ---------------------------------------------------------------------------


def _lint_actions(pack: Pack, out: list[Finding]) -> None:
    levels = set(pack.config.risk.levels)
    seen_recipes: dict[tuple, str] = {}

    for action in pack.actions.values():
        # E_UNKNOWN_RISK
        if action.risk and action.risk not in levels:
            out.append(Finding(ERROR, "E_UNKNOWN_RISK", action.id,
                               f"risk '{action.risk}' not in taxonomy {sorted(levels)}"))

        if action.is_api:
            # E_API_CALL_UNBOUND — the reuse guard: api actions bind to an
            # existing factory/client, never embed their own HTTP.
            if not action.call or ":" not in action.call:
                out.append(Finding(ERROR, "E_API_CALL_UNBOUND", action.id,
                                   "api action 'call' must bind to 'module:function'"))
            if action.role and action.role not in ("setup", "crosscheck"):
                out.append(Finding(ERROR, "E_BAD_API_ROLE", action.id,
                                   f"api role '{action.role}' is not setup|crosscheck"))
            continue

        # --- UI actions ---
        # E_DANGLING_ELEMENT
        for eid in action.elements:
            if eid not in pack.elements:
                out.append(Finding(ERROR, "E_DANGLING_ELEMENT", action.id,
                                   f"references missing element {eid}"))
        # Steps referencing undeclared elements too.
        for step in action.steps:
            if step.element and step.element not in pack.elements:
                out.append(Finding(ERROR, "E_DANGLING_ELEMENT", action.id,
                                   f"step references missing element {step.element}"))

        # E_BROKEN_EDGE
        for edge_kind in ("prev", "next"):
            for target in getattr(action, edge_kind):
                if target not in pack.actions:
                    out.append(Finding(ERROR, "E_BROKEN_EDGE", action.id,
                                       f"{edge_kind}: {target} does not exist"))
                elif pack.actions[target].is_api:
                    out.append(Finding(ERROR, "E_BROKEN_EDGE", action.id,
                                       f"{edge_kind}: {target} is an API action (not a nav node)"))

        # W_NO_STEPS
        if action.elements and not action.steps:
            out.append(Finding(WARNING, "W_NO_STEPS", action.id,
                               "action has elements but no step recipe"))

        # E_PARAM_UNDECLARED — step template refs must resolve to a param/token.
        declared = {p.key for p in action.params}
        tokens = set(pack.config.tokens)
        for step in action.steps:
            refs = iter_template_refs(step.value)
            for wf_val in (step.wait_for or {}).values():
                refs += iter_template_refs(wf_val if isinstance(wf_val, str) else None)
            for ref in refs:
                if "." in ref or ref == "base_url":
                    continue  # runtime capture / injected base url
                if ref not in declared and ref not in tokens:
                    out.append(Finding(ERROR, "E_PARAM_UNDECLARED", action.id,
                                       f"step uses {{{{{ref}}}}} with no matching param"))

        # W_DUPLICATE_RECIPE
        if action.steps:
            sig = tuple((s.op, s.element, s.value, s.scope) for s in action.steps)
            if sig in seen_recipes:
                out.append(Finding(WARNING, "W_DUPLICATE_RECIPE", action.id,
                                   f"identical step recipe to {seen_recipes[sig]} "
                                   "— likely a missed shared action"))
            else:
                seen_recipes[sig] = action.id


def _lint_selectors(pack: Pack, out: list[Finding]) -> None:
    # E_SELECTOR_AMBIGUOUS — two elements in the same app share an identical
    # selector signature (a static proxy for live ambiguity).
    by_sig: dict[tuple, list[str]] = {}
    for el in pack.elements.values():
        key = (el.app,) + el.selector.signature()
        by_sig.setdefault(key, []).append(el.id)
    for ids in by_sig.values():
        if len(ids) > 1:
            first, *rest = sorted(ids)
            for eid in rest:
                out.append(Finding(ERROR, "E_SELECTOR_AMBIGUOUS", eid,
                                   f"identical selector to {first}; add scope/exact name"))


def _lint_captures(pack: Pack, out: list[Finding]) -> None:
    # W_NO_CAPTURE — a template consumes {{captured.x}}/{{alias.x}} that nobody
    # produces anywhere in the pack.
    produced: set[str] = set()
    for action in pack.actions.values():
        for cap in action.captures:
            produced.add(cap.key)
        for step in action.steps:
            if step.op == "capture" and step.key:
                produced.add(step.key)

    def _check(ref_owner: str, template) -> None:
        for ref in iter_template_refs(template):
            if "." not in ref:
                continue
            cap_key = ref.split(".", 1)[1]
            if cap_key not in produced:
                out.append(Finding(WARNING, "W_NO_CAPTURE", ref_owner,
                                   f"consumes {{{{{ref}}}}} that no action produces"))

    for action in pack.actions.values():
        for step in action.steps:
            _check(action.id, step.value)
        if action.is_api and action.call:
            _check(action.id, action.call)
    for flow in pack.flows.values():
        for pstep in flow.path:
            for val in pstep.params.values():
                _check(flow.id, val if isinstance(val, str) else None)


def _lint_flows(pack: Pack, out: list[Finding]) -> None:
    # Build the flow-use graph for cycle detection.
    use_edges: dict[str, list[str]] = {
        fid: [p.use for p in f.path if p.use] for fid, f in pack.flows.items()
    }

    def _has_cycle(start: str) -> bool:
        stack = [(start, {start})]
        while stack:
            node, path = stack.pop()
            for nxt in use_edges.get(node, []):
                if nxt == start or nxt in path:
                    return True
                if nxt in pack.flows:
                    stack.append((nxt, path | {nxt}))
        return False

    for fid, flow in pack.flows.items():
        # E_SUBFLOW_CYCLE
        if _has_cycle(fid):
            out.append(Finding(ERROR, "E_SUBFLOW_CYCLE", fid,
                               "a 'use:' reference recurses"))

        # Unknown refs in the path.
        for pstep in flow.path:
            if pstep.action and pstep.action not in pack.actions:
                out.append(Finding(ERROR, "E_BROKEN_EDGE", fid,
                                   f"path references missing action {pstep.action}"))
            if pstep.use and pstep.use not in pack.flows:
                out.append(Finding(ERROR, "E_BROKEN_EDGE", fid,
                                   f"path uses missing flow {pstep.use}"))

        # E_CAPTURE_COLLISION — an action/subflow that produces captures runs
        # more than once in a flow without an ``as:`` alias.
        counts: dict[str, int] = {}
        for aid, alias in flatten_flow(pack, flow):
            action = pack.action(aid)
            if action is None or not (action.captures or _api_captures(action)):
                continue
            if alias:
                continue
            counts[aid] = counts.get(aid, 0) + 1
        for aid, n in counts.items():
            if n > 1:
                out.append(Finding(ERROR, "E_CAPTURE_COLLISION", fid,
                                   f"{aid} runs {n}x without an 'as:' alias; "
                                   "captures overwrite"))

        # W_UNMET_REQUIRES — reach an action needing a capability with no
        # earlier provider in this path.
        provided: set[str] = set()
        for aid, _alias in flatten_flow(pack, flow):
            action = pack.action(aid)
            if action is None:
                continue
            for need in action.requires:
                if need not in provided:
                    providers = [a.id for a in pack.actions.values() if need in a.provides]
                    hint = f" → {', '.join(providers)}" if providers else ""
                    out.append(Finding(WARNING, "W_UNMET_REQUIRES", fid,
                                       f"{aid} requires '{need}' with no provider in path{hint}"))
            provided.update(action.provides)


def _api_captures(action: Action) -> bool:
    return bool(action.captures)


def _lint_reachability(pack: Pack, out: list[Finding]) -> None:
    # W_UNREACHABLE
    reachable = reachable_actions(pack)
    for action in pack.ui_actions():
        if action.id not in reachable:
            out.append(Finding(WARNING, "W_UNREACHABLE", action.id,
                               "no path from any auth entry flow or root"))


def _lint_coverage(pack: Pack, out: list[Finding]) -> None:
    # W_UI_COVERAGE_BYPASS — a UI action that provides a capability also
    # provided by an API setup action, and which is never exercised through the
    # UI in any flow (provisioned, never UI-tested).
    ui_in_flows: set[str] = set()
    for flow in pack.flows.values():
        for aid, _alias in flatten_flow(pack, flow):
            action = pack.action(aid)
            if action and action.is_ui:
                ui_in_flows.add(aid)

    api_setup_caps: set[str] = set()
    for action in pack.api_actions():
        if action.role == "setup":
            api_setup_caps.update(action.provides)

    for action in pack.ui_actions():
        if action.id in ui_in_flows:
            continue
        if any(cap in api_setup_caps for cap in action.provides):
            out.append(Finding(WARNING, "W_UI_COVERAGE_BYPASS", action.id,
                               "provisioned via an API setup action but never "
                               "exercised through the UI in any flow"))


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def validate(pack: Pack, app: Optional[str] = None) -> ValidationReport:
    """Run every lint pass and return a :class:`ValidationReport`.

    ``app`` optionally scopes action/element findings to one app (flow-level and
    reachability passes always run pack-wide).
    """
    out: list[Finding] = []
    _lint_actions(pack, out)
    _lint_selectors(pack, out)
    _lint_captures(pack, out)
    _lint_flows(pack, out)
    _lint_reachability(pack, out)
    _lint_coverage(pack, out)

    if app is not None:
        def _in_scope(f: Finding) -> bool:
            a = pack.action(f.ref)
            e = pack.element(f.ref)
            if a is not None:
                return a.app == app
            if e is not None:
                return e.app == app
            return True  # flow-level findings are kept
        out = [f for f in out if _in_scope(f)]

    # errors first, then warnings; stable within a severity.
    out.sort(key=lambda f: 0 if f.severity == ERROR else 1)
    return ValidationReport(findings=out)
