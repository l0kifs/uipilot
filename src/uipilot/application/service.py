"""Application layer — use-case orchestration.

Each function here is one use case the presentation layer invokes. This is the
only place that wires **infrastructure** (loading a pack, importing markdown,
resolving capabilities) to **domain** services (compile, validate, verify,
pathfind, usage). It returns domain objects / plain data — never rendered
strings, so any front-end (CLI now, an HTTP API later) can format them.

Dependency direction: application → {domain, infrastructure}. It is imported by
presentation and never imports it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from uipilot.domain import compiler, graph, usage, validation, verification
from uipilot.domain.compiler import CompiledScript
from uipilot.domain.flows import expand_invocations
from uipilot.domain.model import Action, Element, Pack
from uipilot.domain.templating import RuntimeContext
from uipilot.domain.validation import ValidationReport
from uipilot.infrastructure.capabilities import CapabilityRegistry
from uipilot.infrastructure.markdown_importer import import_md, write_seed
from uipilot.infrastructure.pack_loader import load_pack


@dataclass
class PackContext:
    """A loaded pack plus its per-run resolution context."""

    pack: Pack
    runtime: RuntimeContext


def open_pack(path: str | Path, env: Optional[dict] = None) -> PackContext:
    """Load a pack and build its runtime context (env-bound token resolution)."""
    pack = load_pack(path)
    runtime = RuntimeContext(pack.config, env=dict(os.environ if env is None else env))
    return PackContext(pack=pack, runtime=runtime)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def filter_actions(pctx: PackContext, *, app: Optional[str] = None,
                   section: Optional[str] = None, risk: Optional[str] = None,
                   grep: Optional[str] = None, transport: Optional[str] = None) -> list[Action]:
    pack = pctx.pack
    out: list[Action] = []
    for a in pack.actions.values():
        if app and a.app != app:
            continue
        if risk and a.risk != risk:
            continue
        if transport and a.transport != transport:
            continue
        if grep and grep.lower() not in (a.id + " " + a.purpose).lower():
            continue
        if section:
            secs = {pack.elements[e].section for e in a.elements if e in pack.elements}
            if section not in secs:
                continue
        out.append(a)
    return sorted(out, key=lambda a: a.id)


def filter_elements(pctx: PackContext, *, app: Optional[str] = None,
                    action: Optional[str] = None, section: Optional[str] = None,
                    grep: Optional[str] = None) -> list[Element]:
    pack = pctx.pack
    scope_ids: Optional[set] = None
    if action:
        act = pack.action(action)
        if act is None:
            raise KeyError(f"no action named '{action}'")
        scope_ids = set(act.elements)
    out: list[Element] = []
    for e in pack.elements.values():
        if app and e.app != app:
            continue
        if scope_ids is not None and e.id not in scope_ids:
            continue
        if section and e.section != section:
            continue
        if grep and grep.lower() not in (e.id + " " + (e.purpose or "")).lower():
            continue
        out.append(e)
    return sorted(out, key=lambda e: e.id)


def route(pctx: PackContext, src: str, dst: str, max_depth: int = 25) -> dict:
    """Compute a path and enrich it with risk/auth/param facts for consumers."""
    pack = pctx.pack
    result = graph.find_path(pack, src, dst, max_depth=max_depth)
    if not result.found:
        return {"found": False, "reason": result.reason}
    on_path = [pack.actions[a] for a in result.path if a in pack.actions]
    apps = {a.app for a in on_path}
    return {
        "found": True,
        "length": result.length,
        "path": result.path,
        "crosses_app": len(apps) > 1,
        "risk_max": pack.config.risk.max([a.risk for a in on_path]),
        "requires_auth": sorted(apps),
        "params_required": sorted({p.key for a in on_path for p in a.params}),
    }


def uses(pctx: PackContext, ref: str) -> dict:
    return usage.uses(pctx.pack, ref)


def flow_param_manifest(pctx: PackContext, name: str) -> list[dict]:
    """Aggregate every param a flow needs (flow-level + each action's), deduped.

    A cheap lookup that answers "what must I supply?" without compiling — so the
    caller can gather values in one pass instead of the compile-read-recompile
    dance. Secrets never echo a default; ``satisfied_by`` names a capability that
    can mint the value so the agent need not ask a human.
    """
    pack = pctx.pack
    flow = pack.flow(name)
    if flow is None:
        raise KeyError(f"no flow named '{name}'")
    seen: set[str] = set()
    manifest: list[dict] = []

    def _add(param) -> None:
        if param.key in seen:
            return
        seen.add(param.key)
        entry = {
            "key": param.key,
            "type": param.type,
            "required": param.required,
            "secret": param.is_secret,
            "default": None if param.is_secret else param.default,
        }
        if param.enum:
            entry["enum"] = list(param.enum)
        if param.satisfied_by:
            entry["satisfied_by"] = param.satisfied_by
        manifest.append(entry)

    for param in flow.params:
        _add(param)
    for inv in expand_invocations(pack, name):
        action = pack.action(inv.action_id)
        if action is None:
            continue
        for param in action.params:
            _add(param)
    return manifest


# ---------------------------------------------------------------------------
# Compilation / validation / verification
# ---------------------------------------------------------------------------


def compile_script(pctx: PackContext, *, flow: Optional[str] = None,
                   src: Optional[str] = None, dst: Optional[str] = None,
                   actions: Optional[list[str]] = None, **compile_kw) -> CompiledScript:
    """Compile a flow, a path (src→dst), or an explicit action list."""
    pack, rt = pctx.pack, pctx.runtime
    if flow:
        return compiler.compile_flow(pack, rt, flow, **compile_kw)
    if src and dst:
        return compiler.compile_path(pack, rt, src, dst, **compile_kw)
    if actions:
        return compiler.compile_actions(pack, rt, actions, **compile_kw)
    raise ValueError("compile needs a flow, a path (src/dst), or actions")


def validate_pack(pctx: PackContext, app: Optional[str] = None) -> ValidationReport:
    return validation.validate(pctx.pack, app=app)


def verify(pctx: PackContext, *, flow: Optional[str] = None, app: Optional[str] = None,
           action: Optional[str] = None, drive: bool = False,
           allow_gated: bool = False) -> dict:
    return verification.verify_probe(pctx.pack, pctx.runtime, flow=flow, app=app,
                                     action=action, drive=drive, allow_gated=allow_gated)


# ---------------------------------------------------------------------------
# Capabilities / import
# ---------------------------------------------------------------------------


def list_capabilities(pctx: PackContext, check: bool = False) -> list[dict]:
    reg = CapabilityRegistry(pctx.pack.config, pctx.pack.root)
    checks = reg.check_all() if check else {}
    return [{"key": key, "impl": reg.spec(key),
             "error": checks.get(key) if check else None} for key in reg.keys]


def import_markdown(md_file: str | Path, out_dir: str | Path) -> dict:
    result = import_md(md_file)
    written = write_seed(result, out_dir)
    return {
        "structured": result.structured,
        "apps": sorted(result.apps),
        "flows": sorted(result.flows),
        "notes": result.notes,
        "written": [str(p) for p in written],
    }
