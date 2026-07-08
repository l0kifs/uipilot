"""Project bootstrap — ``uipilot init``.

Writes two things into a target project so an agent can start using uipilot:

* a **pack skeleton** (``flowmap.config.yaml`` + ``data/`` + ``capabilities.py``)
  that already loads and passes ``validate`` — the agent fills it on first use;
* one or more **agent instruction files** (a Claude Code skill and/or an
  ``AGENTS.md`` section) carrying the shipped agent guide, so the agent knows how
  to author the pack and drive flows.

Idempotent: an existing pack file is left untouched (never clobber work in
progress) unless ``force``; agent instruction files are always refreshed to the
installed version. This is the one infrastructure module that reads the packaged
``uipilot.templates`` resources and writes into the user's tree.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

# Supported agent instruction targets and where each one's file lives.
AGENT_TARGETS = {
    "claude": ".claude/skills/uipilot/SKILL.md",
    "agents": "AGENTS.md",
}

_MARK_START = "<!-- uipilot:start -->"
_MARK_END = "<!-- uipilot:end -->"

# Pack skeleton: (destination relative path, template resource path).
_SKELETON = [
    ("flowmap.config.yaml", "flowmap.config.yaml"),
    ("data/app.app.yaml", "data/app.app.yaml"),
    ("data/flows.yaml", "data/flows.yaml"),
    ("capabilities.py", "capabilities.py"),
]


def _template(name: str) -> str:
    return resources.files("uipilot.templates").joinpath(name).read_text(encoding="utf-8")


def skill_text() -> str:
    """The shipped agent guide, verbatim (with skill frontmatter)."""
    return _template("skill.md")


def _skill_body() -> str:
    """The guide without YAML frontmatter — for embedding in a plain AGENTS.md."""
    text = skill_text()
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3:].lstrip("\n")
    return text


def init_project(dest: str | Path, agents: list[str], force: bool = False) -> dict:
    """Scaffold a pack skeleton + agent instruction files under ``dest``."""
    root = Path(dest).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    skipped: list[str] = []
    updated: list[str] = []

    # 1. Pack skeleton — never overwrite an existing pack file unless --force.
    for rel, tpl in _SKELETON:
        target = root / rel
        existed = target.exists()
        if existed and not force:
            skipped.append(rel)
            continue
        content = _template(tpl)
        if rel == "flowmap.config.yaml":
            content = content.replace("PACK_NAME", root.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        (updated if existed else created).append(rel)

    # 2. Agent instruction files — always refreshed to the installed version.
    for agent in agents:
        rel = AGENT_TARGETS.get(agent)
        if rel is None:
            continue
        target = root / rel
        existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        if agent == "agents":
            target.write_text(_render_agents_md(target), encoding="utf-8")
        else:
            target.write_text(skill_text(), encoding="utf-8")
        (updated if existed else created).append(rel)

    return {
        "pack": str(root),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "agents": [a for a in agents if a in AGENT_TARGETS],
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
            tail = existing[existing.index(_MARK_END) + len(_MARK_END):]
            return f"{head}{block}{tail.lstrip(chr(10))}"
        sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
        return f"{existing}{sep}{block}"
    return block
