"""`uipilot init`/`update` — scaffold a valid pack + agent instructions, refresh them."""

from __future__ import annotations

from uipilot.domain.validation import validate
from uipilot.infrastructure import scaffold
from uipilot.infrastructure.pack_loader import load_pack

INSTALLED = scaffold.installed_version()


def test_init_scaffolds_a_valid_pack(tmp_path):
    result = scaffold.init_project(tmp_path, agents=["claude", "agents"])
    # pack skeleton lives under .uipilot/, agent files at the project root
    assert set(result["created"]) == {
        ".uipilot/flowmap.config.yaml",
        ".uipilot/data/app.app.yaml",
        ".uipilot/data/flows.yaml",
        ".uipilot/capabilities.py",
        ".claude/skills/uipilot/SKILL.md",
        "AGENTS.md",
    }
    assert result["pack"] == str(tmp_path / ".uipilot")
    # the scaffolded pack loads and passes validate with zero findings
    report = validate(load_pack(tmp_path / ".uipilot"))
    assert report.ok and report.errors == 0 and report.warnings == 0
    # pack name is derived from the project directory
    assert f"pack: {tmp_path.name}" in (tmp_path / ".uipilot/flowmap.config.yaml").read_text()
    # the Claude skill is the shipped guide verbatim (frontmatter intact)
    assert (
        (tmp_path / ".claude/skills/uipilot/SKILL.md").read_text().startswith("---\nname: uipilot")
    )
    # AGENTS.md wraps the guide body in replaceable markers
    agents_md = (tmp_path / "AGENTS.md").read_text()
    assert scaffold._MARK_START in agents_md and scaffold._MARK_END in agents_md


def test_init_is_idempotent_and_force_overwrites(tmp_path):
    scaffold.init_project(tmp_path, agents=["claude"])
    # user starts filling the pack
    (tmp_path / ".uipilot/flowmap.config.yaml").write_text("pack: mine\napps: []\n")

    again = scaffold.init_project(tmp_path, agents=["claude"])
    assert ".uipilot/flowmap.config.yaml" in again["skipped"]  # never clobbered
    assert ".claude/skills/uipilot/SKILL.md" in again["updated"]  # skill refreshed
    assert (tmp_path / ".uipilot/flowmap.config.yaml").read_text() == "pack: mine\napps: []\n"

    forced = scaffold.init_project(tmp_path, agents=[], force=True)
    assert ".uipilot/flowmap.config.yaml" in forced["updated"]  # --force overwrites
    assert f"pack: {tmp_path.name}" in (tmp_path / ".uipilot/flowmap.config.yaml").read_text()


def test_agents_md_block_is_replaced_not_duplicated(tmp_path):
    existing = tmp_path / "AGENTS.md"
    existing.write_text("# My project rules\n\nBe nice.\n")
    scaffold.init_project(tmp_path, agents=["agents"])
    scaffold.init_project(tmp_path, agents=["agents"])  # twice
    text = existing.read_text()
    assert "# My project rules" in text  # prior content preserved
    assert text.count(scaffold._MARK_START) == 1  # exactly one block


def test_unknown_agent_is_ignored(tmp_path):
    result = scaffold.init_project(tmp_path, agents=["bogus"])
    assert result["agents"] == []
    assert not (tmp_path / ".claude").exists()


def test_scaffolded_files_carry_version_stamps(tmp_path):
    scaffold.init_project(tmp_path, agents=["claude", "agents"])
    skill = (tmp_path / ".claude/skills/uipilot/SKILL.md").read_text()
    # stamped with the installed version, after the frontmatter (skill loaders
    # require the frontmatter to open the file)
    assert skill.startswith("---\nname: uipilot")
    assert scaffold.stamped_version(skill) == INSTALLED
    assert "do not edit by hand" in skill
    assert scaffold.stamped_version((tmp_path / "AGENTS.md").read_text()) == INSTALLED
    # the pack config records the scaffolding version for future migrations
    config = (tmp_path / ".uipilot/flowmap.config.yaml").read_text()
    assert f"# scaffolded by uipilot v{INSTALLED}" in config
    # ... and still loads + validates cleanly with the stamp comment in place
    assert validate(load_pack(tmp_path / ".uipilot")).ok


def test_update_refreshes_detected_agent_files_only(tmp_path):
    scaffold.init_project(tmp_path, agents=["claude", "agents"])
    # simulate files scaffolded by an older uipilot
    skill_path = tmp_path / ".claude/skills/uipilot/SKILL.md"
    skill_path.write_text(skill_path.read_text().replace(f"uipilot:v{INSTALLED}", "uipilot:v0.1.0"))
    (tmp_path / ".uipilot/data/flows.yaml").write_text("flows: {}\n")  # user's pack work

    result = scaffold.update_project(tmp_path)
    assert result["version"] == INSTALLED
    assert {r["file"]: (r["from"], r["to"]) for r in result["refreshed"]} == {
        ".claude/skills/uipilot/SKILL.md": ("0.1.0", INSTALLED),
        "AGENTS.md": (INSTALLED, INSTALLED),
    }
    assert scaffold.stamped_version(skill_path.read_text()) == INSTALLED
    # pack files are never touched by update
    assert (tmp_path / ".uipilot/data/flows.yaml").read_text() == "flows: {}\n"
    assert result["pack_scaffolded"] == INSTALLED


def test_update_finds_nothing_in_a_fresh_dir(tmp_path):
    result = scaffold.update_project(tmp_path)
    assert result["refreshed"] == []
    assert result["pack_scaffolded"] is None
    assert not (tmp_path / ".claude").exists()


def test_update_ignores_foreign_agents_md_but_can_add_targets(tmp_path):
    # a project's own AGENTS.md (no uipilot markers) is not uipilot's to rewrite
    (tmp_path / "AGENTS.md").write_text("# House rules\n")
    scaffold.init_project(tmp_path, agents=["claude"])
    result = scaffold.update_project(tmp_path)
    assert [r["file"] for r in result["refreshed"]] == [".claude/skills/uipilot/SKILL.md"]
    assert (tmp_path / "AGENTS.md").read_text() == "# House rules\n"

    # --agent opts the file in: the block is appended, house rules preserved
    result = scaffold.update_project(tmp_path, agents=["agents", "bogus"])
    assert [r["file"] for r in result["refreshed"]] == [
        ".claude/skills/uipilot/SKILL.md",
        "AGENTS.md",
    ]
    text = (tmp_path / "AGENTS.md").read_text()
    assert "# House rules" in text and scaffold._MARK_START in text
