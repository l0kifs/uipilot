"""Project bootstrap — ``uipilot init`` — and refresh — ``uipilot update``.

Writes two things into a target project so an agent can start using uipilot:

* a **pack skeleton** (``flowmap.config.yaml`` + ``data/`` + ``capabilities.py``)
  under ``.uipilot/`` that already loads and passes ``validate`` — the agent
  fills it on first use;
* one or more **agent instruction files** (a Claude Code skill and/or an
  ``AGENTS.md`` section) carrying the shipped agent guide, so the agent knows how
  to author the pack and drive flows.

Idempotent: an existing pack file is left untouched (never clobber work in
progress) unless ``force``; agent instruction files are always refreshed to the
installed version and stamped with it, so ``uipilot update`` can detect and
refresh stale copies after a tool upgrade. This is the one infrastructure module
that reads the packaged ``uipilot.templates`` resources and writes into the
user's tree.
"""

from __future__ import annotations

import re
from importlib import metadata, resources
from pathlib import Path
from typing import Optional

from uipilot.infrastructure.pack_loader import PACK_SUBDIR

# Supported agent instruction targets and where each one's file lives.
AGENT_TARGETS = {
    "claude": ".claude/skills/uipilot/SKILL.md",
    "agents": "AGENTS.md",
}

_MARK_START = "<!-- uipilot:start -->"
_MARK_END = "<!-- uipilot:end -->"

# Version stamps: agent instruction files carry an HTML-comment stamp, the pack
# config a YAML-comment stamp. Both are machine-parseable so `update` can report
# installed vs. scaffolded versions.
_STAMP_RE = re.compile(r"<!-- uipilot:v(\S+) ")
_PACK_STAMP_RE = re.compile(r"# scaffolded by uipilot v(\S+)")

# Pack skeleton: (destination relative path, template resource path).
_SKELETON = [
    ("flowmap.config.yaml", "flowmap.config.yaml"),
    ("data/app.app.yaml", "data/app.app.yaml"),
    ("data/flows.yaml", "data/flows.yaml"),
    ("capabilities.py", "capabilities.py"),
]


def _template(name: str) -> str:
    return resources.files("uipilot.templates").joinpath(name).read_text(encoding="utf-8")


def installed_version() -> str:
    """The installed uipilot distribution version (best effort)."""
    try:
        return metadata.version("uipilot")
    except metadata.PackageNotFoundError:  # pragma: no cover - running unpackaged
        return "unknown"


def _stamp() -> str:
    return (
        f"<!-- uipilot:v{installed_version()} — generated file, do not edit by hand; "
        "refresh with `uipilot update` after upgrading uipilot -->"
    )


def stamped_version(text: str) -> Optional[str]:
    """The version recorded in a scaffolded file's stamp, if any."""
    m = _STAMP_RE.search(text)
    return m.group(1) if m else None


def skill_text() -> str:
    """The shipped agent guide with a version stamp under its skill frontmatter."""
    text = _template("skill.md")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            insert_at = text.index("\n", end + 1) + 1
            return f"{text[:insert_at]}{_stamp()}\n{text[insert_at:]}"
    return f"{_stamp()}\n{text}"  # pragma: no cover - shipped skill has frontmatter


def _skill_body() -> str:
    """The guide without YAML frontmatter — for embedding in a plain AGENTS.md."""
    text = skill_text()
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3 :].lstrip("\n")
    return text


def init_project(dest: str | Path, agents: list[str], force: bool = False) -> dict:
    """Scaffold a pack skeleton + agent instruction files under ``dest``."""
    root = Path(dest).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    skipped: list[str] = []
    updated: list[str] = []

    # 1. Pack skeleton — scaffolded under `<project>/.uipilot/` and never
    #    overwritten unless --force. Reported paths stay relative to the project
    #    root (e.g. `.uipilot/flowmap.config.yaml`).
    pack_root = root / PACK_SUBDIR
    for rel, tpl in _SKELETON:
        target = pack_root / rel
        rel_display = f"{PACK_SUBDIR}/{rel}"
        existed = target.exists()
        if existed and not force:
            skipped.append(rel_display)
            continue
        content = _template(tpl)
        if rel == "flowmap.config.yaml":
            content = content.replace("PACK_NAME", root.name)
            content = (
                f"# scaffolded by uipilot v{installed_version()} — this file is yours; "
                "`uipilot update` never touches it.\n" + content
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        (updated if existed else created).append(rel_display)

    # 2. Agent instruction files — always refreshed to the installed version.
    for agent in agents:
        if agent not in AGENT_TARGETS:
            continue
        existed = (root / AGENT_TARGETS[agent]).exists()
        rel = _write_agent(root, agent)
        (updated if existed else created).append(rel)

    return {
        "pack": str(pack_root),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "agents": [a for a in agents if a in AGENT_TARGETS],
    }


def _write_agent(root: Path, agent: str) -> str:
    """Write one agent instruction file at the installed version; returns its rel path."""
    rel = AGENT_TARGETS[agent]
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if agent == "agents":
        target.write_text(_render_agents_md(target), encoding="utf-8")
    else:
        target.write_text(skill_text(), encoding="utf-8")
    return rel


def update_project(dest: str | Path, agents: Optional[list[str]] = None) -> dict:
    """Refresh agent instruction files to the installed version — ``uipilot update``.

    Auto-detects which instruction files the project already has (the Claude
    skill; an ``AGENTS.md`` carrying uipilot's marked block) and rewrites them;
    ``agents`` adds targets that don't exist yet. Pack files are never touched —
    ``pack_scaffolded`` in the result just reports the version recorded by
    ``init`` so callers can surface schema drift.
    """
    root = Path(dest).expanduser().resolve()

    detected = []
    for agent, rel in AGENT_TARGETS.items():
        target = root / rel
        if not target.exists():
            continue
        if agent == "agents" and _MARK_START not in target.read_text(encoding="utf-8"):
            continue
        detected.append(agent)
    requested = [a for a in (agents or []) if a in AGENT_TARGETS]
    targets = list(dict.fromkeys(detected + requested))

    refreshed: list[dict] = []
    for agent in targets:
        target = root / AGENT_TARGETS[agent]
        previous = stamped_version(target.read_text(encoding="utf-8")) if target.exists() else None
        rel = _write_agent(root, agent)
        refreshed.append({"file": rel, "from": previous, "to": installed_version()})

    pack_config = root / PACK_SUBDIR / "flowmap.config.yaml"
    pack_scaffolded = None
    if pack_config.exists():
        m = _PACK_STAMP_RE.search(pack_config.read_text(encoding="utf-8"))
        pack_scaffolded = m.group(1) if m else None

    return {
        "version": installed_version(),
        "refreshed": refreshed,
        "pack_scaffolded": pack_scaffolded,
    }


def _render_agents_md(target: Path) -> str:
    """Insert or replace uipilot's marked block in an ``AGENTS.md``."""
    block = (
        f"{_MARK_START}\n"
        "# uipilot\n\n"
        "This project uses **uipilot** to drive its web UI. Follow this guide when "
        "asked to run/automate/test a flow, map the app, or check UI drift.\n\n"
        f"{_skill_body().strip()}\n"
        f"{_MARK_END}\n"
    )
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if _MARK_START in existing and _MARK_END in existing:
            head = existing[: existing.index(_MARK_START)]
            tail = existing[existing.index(_MARK_END) + len(_MARK_END) :]
            return f"{head}{block}{tail.lstrip(chr(10))}"
        sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
        return f"{existing}{sep}{block}"
    return block
