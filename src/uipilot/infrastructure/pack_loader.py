"""Load a pack (config + YAML) into the domain model.

This is the *infrastructure* boundary: it is the only place that touches YAML,
the filesystem, and pack directory layout. It produces pure domain objects
(:class:`~uipilot.domain.model.Pack`) and depends inward on the domain only.

A *pack* is a directory containing:

    flowmap.config.yaml     # binds apps, tokens, risk taxonomy, capabilities
    data/<app>.app.yaml     # one file per app: app header + elements + actions
    data/flows.yaml         # named multi-app flows (+ optional shared actions)
    capabilities.py         # (optional) named auth adapters the engine calls

The loader is tolerant of *incomplete* models (dangling refs load fine) so the
domain linter can report every problem at once; only genuinely unparseable input
raises :class:`~uipilot.domain.errors.PackError`.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from uipilot.domain.errors import PackError
from uipilot.domain.model import (
    Action,
    App,
    Auth,
    CapabilitySpec,
    Capture,
    Config,
    Element,
    Flow,
    Pack,
    Param,
    PathStep,
    RiskTaxonomy,
    Selector,
    Step,
    Token,
)

CONFIG_FILENAME = "flowmap.config.yaml"
DATA_DIR = "data"
FLOWS_FILENAME = "flows.yaml"


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise PackError(f"missing file: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:  # pragma: no cover - passthrough
        raise PackError(f"could not parse {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise PackError(f"{path}: expected a mapping at the top level")
    return data


# ---------------------------------------------------------------------------
# Parsers (dict -> dataclass)
# ---------------------------------------------------------------------------


def _parse_selector(raw: dict, *, where: str) -> Selector:
    if not isinstance(raw, dict):
        raise PackError(f"{where}: selector must be a mapping")
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
            raise PackError(f"{where}: selector needs a strategy")
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


def _parse_param(raw: dict, *, where: str) -> Param:
    if not isinstance(raw, dict) or "key" not in raw:
        raise PackError(f"{where}: param needs a 'key'")
    return Param(
        key=raw["key"],
        type=raw.get("type", "string"),
        required=bool(raw.get("required", False)),
        default=raw.get("default"),
        enum=list(raw.get("enum", []) or []),
    )


_STEP_KNOWN = {"op", "element", "value", "wait_for", "scope", "optional",
               "key", "from", "pattern", "path"}


def _parse_step(raw: dict, *, where: str) -> Step:
    if not isinstance(raw, dict) or "op" not in raw:
        raise PackError(f"{where}: step needs an 'op'")
    wait_for = raw.get("wait_for")
    if isinstance(wait_for, str):
        wait_for = {"text": wait_for}
    extra = {k: v for k, v in raw.items() if k not in _STEP_KNOWN}
    return Step(
        op=raw["op"],
        element=raw.get("element"),
        value=raw.get("value"),
        wait_for=wait_for,
        scope=raw.get("scope"),
        optional=bool(raw.get("optional", False)),
        key=raw.get("key"),
        from_=raw.get("from"),
        pattern=raw.get("pattern"),
        path=raw.get("path"),
        args=extra,
    )


def _parse_capture(raw: dict, *, where: str) -> Capture:
    if not isinstance(raw, dict) or "key" not in raw:
        raise PackError(f"{where}: capture needs a 'key'")
    return Capture(
        key=raw["key"],
        from_=raw.get("from", "url"),
        pattern=raw.get("pattern"),
        path=raw.get("path"),
        element=raw.get("element"),
    )


def _parse_action(action_id: str, raw: dict, *, default_app: str) -> Action:
    if not isinstance(raw, dict):
        raise PackError(f"action {action_id}: expected a mapping")
    where = f"action {action_id}"
    transport = raw.get("transport", "ui")
    return Action(
        id=action_id,
        app=raw.get("app", default_app),
        transport=transport,
        purpose=raw.get("purpose", ""),
        risk=raw.get("risk", "low"),
        route=raw.get("route"),
        elements=list(raw.get("elements", []) or []),
        prev=list(raw.get("prev", []) or []),
        next=list(raw.get("next", []) or []),
        steps=[_parse_step(s, where=where) for s in raw.get("steps", []) or []],
        role=raw.get("role"),
        call=raw.get("call"),
        params=[_parse_param(p, where=where) for p in raw.get("params", []) or []],
        captures=[_parse_capture(c, where=where) for c in raw.get("captures", []) or []],
        requires=list(raw.get("requires", []) or []),
        provides=list(raw.get("provides", []) or []),
    )


def _parse_path_step(raw, *, where: str) -> PathStep:
    if isinstance(raw, str):
        return PathStep(action=raw)
    if not isinstance(raw, dict):
        raise PackError(f"{where}: path entry must be a string or mapping")
    if "use" in raw:
        return PathStep(
            use=raw["use"],
            alias=raw.get("as"),
            params=dict(raw.get("params", raw.get("args", {})) or {}),
        )
    if "action" in raw:
        params = dict(raw.get("params", {}) or {})
        params.update(raw.get("args", {}) or {})
        return PathStep(
            action=raw["action"],
            alias=raw.get("as"),
            role=raw.get("role"),
            params=params,
        )
    raise PackError(f"{where}: path entry needs 'action' or 'use'")


def _parse_flow(flow_id: str, raw: dict) -> Flow:
    if not isinstance(raw, dict):
        raise PackError(f"flow {flow_id}: expected a mapping")
    where = f"flow {flow_id}"
    return Flow(
        id=flow_id,
        app=raw.get("app"),
        description=raw.get("description", ""),
        path=[_parse_path_step(p, where=where) for p in raw.get("path", []) or []],
        params=[_parse_param(p, where=where) for p in raw.get("params", []) or []],
        guard=raw.get("guard"),
    )


def _parse_app_header(raw: dict) -> App:
    if not isinstance(raw, dict) or "id" not in raw:
        raise PackError("app header needs an 'id'")
    base = raw.get("base_url", {}) or {}
    auth_raw = raw.get("auth") or {}
    auth = Auth(
        entry_flow=auth_raw.get("entry_flow"),
        storage_state_key=auth_raw.get("storage_state_key"),
    ) if auth_raw else None
    return App(
        id=raw["id"],
        id_prefix=raw.get("id_prefix", raw["id"]),
        base_url_env=base.get("env"),
        base_url_default=base.get("default"),
        package=raw.get("package"),
        auth=auth,
    )


def _parse_config(raw: dict, *, where: str) -> Config:
    if "apps" not in raw:
        raise PackError(f"{where}: config needs an 'apps' list")
    tokens: dict[str, Token] = {}
    for key, spec in (raw.get("tokens", {}) or {}).items():
        spec = spec or {}
        tokens[key] = Token(
            key=key,
            from_=spec.get("from", "env"),
            name=spec.get("name"),
            default=spec.get("default"),
        )
    risk_raw = raw.get("risk", {}) or {}
    risk = RiskTaxonomy(
        levels=list(risk_raw.get("levels", ["low", "destructive"])),
        gated=list(risk_raw.get("gated", ["destructive"])),
    )
    caps: dict[str, CapabilitySpec] = {}
    for key, spec in (raw.get("capabilities", {}) or {}).items():
        spec = spec or {}
        impl = spec.get("impl")
        if not impl:
            raise PackError(f"{where}: capability '{key}' needs an 'impl'")
        caps[key] = CapabilitySpec(key=key, impl=impl)
    return Config(
        pack=raw.get("pack", "pack"),
        apps=list(raw["apps"]),
        tokens=tokens,
        risk=risk,
        capabilities=caps,
    )


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_pack(pack_dir: str | Path) -> Pack:
    """Load a pack from ``pack_dir`` into a :class:`Pack`.

    Raises :class:`PackError` only on unrecoverable problems (missing config,
    unknown app referenced in ``apps:``, unparseable YAML). Model-level
    inconsistencies are left intact for the domain linter to report.
    """
    root = Path(pack_dir).expanduser().resolve()
    config_path = root / CONFIG_FILENAME
    config = _parse_config(_read_yaml(config_path), where=str(config_path))

    apps: dict[str, App] = {}
    elements: dict[str, Element] = {}
    actions: dict[str, Action] = {}
    flows: dict[str, Flow] = {}

    data_dir = root / DATA_DIR
    for app_id in config.apps:
        app_path = data_dir / f"{app_id}.app.yaml"
        raw = _read_yaml(app_path)
        header = raw.get("app")
        if not header:
            raise PackError(f"{app_path}: missing 'app:' header")
        app = _parse_app_header(header)
        if app.id != app_id:
            raise PackError(
                f"{app_path}: app id '{app.id}' does not match filename '{app_id}'"
            )
        apps[app_id] = app

        for eid, espec in (raw.get("elements", {}) or {}).items():
            espec = espec or {}
            elements[eid] = Element(
                id=eid,
                app=app_id,
                type=espec.get("type", "element"),
                selector=_parse_selector(espec.get("selector", {}), where=f"element {eid}"),
                section=espec.get("section"),
                purpose=espec.get("purpose"),
            )
        for aid, aspec in (raw.get("actions", {}) or {}).items():
            actions[aid] = _parse_action(aid, aspec or {}, default_app=app_id)

    flows_path = data_dir / FLOWS_FILENAME
    if flows_path.exists():
        raw = _read_yaml(flows_path)
        for aid, aspec in (raw.get("actions", {}) or {}).items():
            default_app = (aspec or {}).get("app") or (config.apps[0] if config.apps else "")
            actions[aid] = _parse_action(aid, aspec or {}, default_app=default_app)
        for fid, fspec in (raw.get("flows", {}) or {}).items():
            flows[fid] = _parse_flow(fid, fspec or {})

    return Pack(
        config=config,
        apps=apps,
        elements=elements,
        actions=actions,
        flows=flows,
        root=root,
    )
