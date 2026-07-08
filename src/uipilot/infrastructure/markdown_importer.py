"""One-time importer: seed pack YAML from a retired Markdown flow map.

``UI_FLOW_MAP.md`` is Markdown — a good human view but a poor database. This is
a **one-shot** seeding aid, not a maintained sync: after import the YAML is
authoritative and the MD is dropped (design §7, DEC-UICLI-1).

Strategy, most-reliable first:

1. **Embedded YAML fences.** Any ```yaml block whose top-level keys are among
   ``app|elements|actions|flows`` is parsed and merged. This is lossless and is
   the recommended way to make an MD importable.
2. **Heuristic id harvest (fallback).** When no structured blocks exist, element
   ids (``<prefix>_<...>``) and action ids (``act_<...>``) are harvested from the
   prose and emitted as *stub* entries grouped by prefix, with ``TODO`` markers.

The result is always written with a ``SEED — review before use`` banner; a human
tightens selectors and edges afterward.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_FENCE_RE = re.compile(r"```ya?ml\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_ELEMENT_ID_RE = re.compile(
    r"\b([a-z]{2,5})_((?:btn|input|toast|dialog|select|link|"
    r"tab|field|checkbox|menu|text|label|row)_[a-z0-9_]+)\b"
)
_ACTION_ID_RE = re.compile(r"\bact_([a-z]{2,5})_([a-z0-9_]+)\b")

_STRUCTURAL_KEYS = {"app", "elements", "actions", "flows"}


@dataclass
class ImportResult:
    apps: dict = field(default_factory=dict)  # app_id -> {app, elements, actions}
    flows: dict = field(default_factory=dict)  # flow_id -> spec
    structured: bool = False  # True if YAML fences were found
    notes: list = field(default_factory=list)


def _merge_structured(blocks: list[dict], result: ImportResult) -> None:
    for block in blocks:
        if not isinstance(block, dict):
            continue
        # An app header in the block scopes that block's elements/actions.
        block_app = None
        app_hdr = block.get("app")
        if app_hdr and isinstance(app_hdr, dict) and app_hdr.get("id"):
            block_app = app_hdr["id"]
            entry = result.apps.setdefault(
                block_app, {"app": app_hdr, "elements": {}, "actions": {}}
            )
            entry["app"] = app_hdr

        for eid, espec in (block.get("elements") or {}).items():
            aid = block_app or _prefix_of(eid) or "app"
            result.apps.setdefault(aid, {"app": None, "elements": {}, "actions": {}})
            result.apps[aid]["elements"][eid] = espec
        for aid_key, aspec in (block.get("actions") or {}).items():
            app_id = (aspec or {}).get("app") or block_app or _action_prefix(aid_key) or "app"
            result.apps.setdefault(app_id, {"app": None, "elements": {}, "actions": {}})
            result.apps[app_id]["actions"][aid_key] = aspec
        for fid, fspec in (block.get("flows") or {}).items():
            result.flows[fid] = fspec
    result.structured = True


def _prefix_of(element_id: str) -> str | None:
    m = re.match(r"([a-z]{2,5})_", element_id)
    return m.group(1) if m else None


def _action_prefix(action_id: str) -> str | None:
    m = _ACTION_ID_RE.match(action_id) or re.match(r"act_([a-z]{2,5})_", action_id)
    return m.group(1) if m else None


def _harvest_heuristic(text: str, result: ImportResult) -> None:
    for m in _ELEMENT_ID_RE.finditer(text):
        prefix, rest = m.group(1), m.group(2)
        eid = f"{prefix}_{rest}"
        entry = result.apps.setdefault(prefix, {"app": None, "elements": {}, "actions": {}})
        entry["elements"].setdefault(
            eid,
            {
                "type": rest.split("_", 1)[0],
                "selector": {"strategy": "role", "role": "TODO", "name": "TODO"},
                "purpose": "TODO seeded from MD",
            },
        )
    for m in _ACTION_ID_RE.finditer(text):
        prefix, rest = m.group(1), m.group(2)
        aid = f"act_{prefix}_{rest}"
        entry = result.apps.setdefault(prefix, {"app": None, "elements": {}, "actions": {}})
        entry["actions"].setdefault(
            aid,
            {
                "app": prefix,
                "purpose": "TODO seeded from MD",
                "risk": "low",
                "elements": [],
                "prev": [],
                "next": [],
                "steps": [],
            },
        )
    result.notes.append("heuristic harvest: tighten selectors/edges before use")


def import_md(md_path: str | Path) -> ImportResult:
    path = Path(md_path).expanduser().resolve()
    text = path.read_text(encoding="utf-8")
    result = ImportResult()

    blocks = []
    for m in _FENCE_RE.finditer(text):
        try:
            data = yaml.safe_load(m.group(1))
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and (_STRUCTURAL_KEYS & set(data)):
            blocks.append(data)

    if blocks:
        _merge_structured(blocks, result)
    else:
        _harvest_heuristic(text, result)

    # Fill in minimal app headers where missing.
    for aid, entry in result.apps.items():
        if not entry.get("app"):
            entry["app"] = {
                "id": aid,
                "id_prefix": aid,
                "base_url": {"env": f"{aid.upper()}_UI_URL", "default": "http://127.0.0.1:3000"},
            }
    return result


_BANNER = (
    "# SEED — generated by `uipilot import-md`. Review before use:\n"
    "# tighten selectors, wire prev/next edges, add step recipes.\n"
)


def write_seed(result: ImportResult, out_dir: str | Path) -> list[Path]:
    """Write the import result into a pack ``data/`` layout. Returns files written."""
    out = Path(out_dir).expanduser().resolve()
    data_dir = out / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for aid, entry in result.apps.items():
        doc = {"app": entry["app"]}
        if entry["elements"]:
            doc["elements"] = entry["elements"]
        if entry["actions"]:
            doc["actions"] = entry["actions"]
        app_path = data_dir / f"{aid}.app.yaml"
        app_path.write_text(_BANNER + yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
        written.append(app_path)

    if result.flows:
        flows_path = data_dir / "flows.yaml"
        flows_path.write_text(
            _BANNER + yaml.safe_dump({"flows": result.flows}, sort_keys=False), encoding="utf-8"
        )
        written.append(flows_path)

    # A starter config so the seed loads immediately.
    config = {
        "pack": out.name,
        "apps": sorted(result.apps),
        "tokens": {
            "prefix": {"from": "env", "name": "TEST_ENTITY_PREFIX", "default": "uipilot"},
            "seq": {"from": "counter"},
        },
        "risk": {
            "levels": ["low", "admin-control", "credential", "destructive", "money-moving"],
            "gated": ["destructive", "money-moving"],
        },
    }
    config_path = out / "flowmap.config.yaml"
    if not config_path.exists():
        config_path.write_text(_BANNER + yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        written.append(config_path)
    return written
