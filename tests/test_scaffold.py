"""`uipilot init` — project bootstrap: scaffold a valid pack + agent instructions."""

from __future__ import annotations

from typer.testing import CliRunner

from uipilot.domain.validation import validate
from uipilot.infrastructure import scaffold
from uipilot.infrastructure.pack_loader import load_pack
from uipilot.presentation.cli import app

runner = CliRunner()


def test_init_scaffolds_a_valid_pack(tmp_path):
    result = scaffold.init_project(tmp_path, agents=["claude", "agents"])
    # skeleton + both agent files created
    assert set(result["created"]) == {
        "flowmap.config.yaml", "data/app.app.yaml", "data/flows.yaml",
        "capabilities.py", ".claude/skills/uipilot/SKILL.md", "AGENTS.md",
    }
    # the scaffolded pack loads and passes validate with zero findings
    report = validate(load_pack(tmp_path))
    assert report.ok and report.errors == 0 and report.warnings == 0
    # pack name is derived from the directory
    assert f"pack: {tmp_path.name}" in (tmp_path / "flowmap.config.yaml").read_text()
    # the Claude skill is the shipped guide verbatim (frontmatter intact)
    assert (tmp_path / ".claude/skills/uipilot/SKILL.md").read_text().startswith("---\nname: uipilot")
    # AGENTS.md wraps the guide body in replaceable markers
    agents_md = (tmp_path / "AGENTS.md").read_text()
    assert scaffold._MARK_START in agents_md and scaffold._MARK_END in agents_md


def test_init_is_idempotent_and_force_overwrites(tmp_path):
    scaffold.init_project(tmp_path, agents=["claude"])
    # user starts filling the pack
    (tmp_path / "flowmap.config.yaml").write_text("pack: mine\napps: []\n")

    again = scaffold.init_project(tmp_path, agents=["claude"])
    assert "flowmap.config.yaml" in again["skipped"]           # never clobbered
    assert ".claude/skills/uipilot/SKILL.md" in again["updated"]  # skill refreshed
    assert (tmp_path / "flowmap.config.yaml").read_text() == "pack: mine\napps: []\n"

    forced = scaffold.init_project(tmp_path, agents=[], force=True)
    assert "flowmap.config.yaml" in forced["updated"]           # --force overwrites
    assert f"pack: {tmp_path.name}" in (tmp_path / "flowmap.config.yaml").read_text()


def test_agents_md_block_is_replaced_not_duplicated(tmp_path):
    existing = tmp_path / "AGENTS.md"
    existing.write_text("# My project rules\n\nBe nice.\n")
    scaffold.init_project(tmp_path, agents=["agents"])
    scaffold.init_project(tmp_path, agents=["agents"])  # twice
    text = existing.read_text()
    assert "# My project rules" in text                        # prior content preserved
    assert text.count(scaffold._MARK_START) == 1               # exactly one block


def test_unknown_agent_is_ignored(tmp_path):
    result = scaffold.init_project(tmp_path, agents=["bogus"])
    assert result["agents"] == []
    assert not (tmp_path / ".claude").exists()


def test_init_cli_prints_friendly_summary(tmp_path):
    res = runner.invoke(app, ["init", str(tmp_path), "--agent", "claude"])
    assert res.exit_code == 0
    assert "uipilot ready" in res.stdout
    assert "flowmap.config.yaml" in res.stdout
