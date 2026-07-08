"""Cover the remaining linter finding codes and the app-scoping filter.

``test_validate.py`` pins the headline error codes; this file exercises the
warning-level passes and the less-common error branches so the linter's full
contract (the CI guard against map rot) is under test.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from uipilot.domain.validation import ERROR, validate
from uipilot.infrastructure.pack_loader import load_pack

DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo"


def _broken(tmp_path, mutate):
    shutil.copytree(DEMO, tmp_path, dirs_exist_ok=True)
    mutate(tmp_path)
    return load_pack(tmp_path)


def _codes(pack):
    return {f.code for f in validate(pack).findings}


def _edit_console(root, fn):
    p = root / "data" / "console.app.yaml"
    doc = yaml.safe_load(p.read_text())
    fn(doc)
    p.write_text(yaml.safe_dump(doc))


def _edit_flows(root, fn):
    p = root / "data" / "flows.yaml"
    doc = yaml.safe_load(p.read_text())
    fn(doc)
    p.write_text(yaml.safe_dump(doc))


def test_unknown_risk_error(tmp_path):
    pack = _broken(
        tmp_path,
        lambda root: _edit_console(
            root, lambda d: d["actions"]["act_cs_create_project"].__setitem__("risk", "bogus")
        ),
    )
    assert "E_UNKNOWN_RISK" in _codes(pack)


def test_bad_api_role_error(tmp_path):
    pack = _broken(
        tmp_path,
        lambda root: _edit_flows(
            root, lambda d: d["actions"]["api_create_project"].__setitem__("role", "weird")
        ),
    )
    assert "E_BAD_API_ROLE" in _codes(pack)


def test_no_steps_warning(tmp_path):
    def mutate(root):
        _edit_console(
            root, lambda d: d["actions"]["act_cs_view_dashboard"].__setitem__("steps", [])
        )

    assert "W_NO_STEPS" in _codes(_broken(tmp_path, mutate))


def test_no_capture_warning(tmp_path):
    def mutate(root):
        _edit_console(
            root,
            lambda d: d["actions"]["act_cs_create_project"]["steps"][2].__setitem__(
                "value", "{{captured.nobody_makes_this}}"
            ),
        )

    assert "W_NO_CAPTURE" in _codes(_broken(tmp_path, mutate))


def test_duplicate_recipe_warning(tmp_path):
    def mutate(root):
        def fn(d):
            # clone an existing recipe onto a fresh action → identical signature
            src = d["actions"]["act_cs_credentials"]
            d["actions"]["act_cs_credentials_twin"] = {
                "purpose": "twin",
                "route": "/projects",
                "elements": src["elements"],
                "prev": [],
                "next": [],
                "steps": src["steps"],
            }

        _edit_console(root, fn)

    assert "W_DUPLICATE_RECIPE" in _codes(_broken(tmp_path, mutate))


def test_unreachable_warning(tmp_path):
    def mutate(root):
        # a mutually-referencing pair with no prev-less root and no entry flow
        def fn(d):
            d["actions"]["act_cs_island_a"] = {
                "purpose": "island",
                "route": "/x",
                "elements": [],
                "steps": [],
                "prev": ["act_cs_island_b"],
                "next": ["act_cs_island_b"],
            }
            d["actions"]["act_cs_island_b"] = {
                "purpose": "island",
                "route": "/x",
                "elements": [],
                "steps": [],
                "prev": ["act_cs_island_a"],
                "next": ["act_cs_island_a"],
            }

        _edit_console(root, fn)

    assert "W_UNREACHABLE" in _codes(_broken(tmp_path, mutate))


def test_ui_coverage_bypass_warning(tmp_path):
    def mutate(root):
        # a UI action provides `project` (an API setup cap) but is in no flow
        def fn(d):
            d["actions"]["act_cs_orphan_project"] = {
                "purpose": "provisions a project via UI but never flow-tested",
                "route": "/projects",
                "elements": [],
                "steps": [],
                "prev": [],
                "next": [],
                "provides": ["project"],
            }

        _edit_console(root, fn)

    assert "W_UI_COVERAGE_BYPASS" in _codes(_broken(tmp_path, mutate))


def test_app_scope_filters_out_of_scope_findings(tmp_path):
    def mutate(root):
        _edit_console(
            root, lambda d: d["actions"]["act_cs_create_project"]["elements"].append("cs_ghost")
        )
        p = root / "data" / "portal.app.yaml"
        doc = yaml.safe_load(p.read_text())
        doc["actions"]["act_pt_open_wallets"]["next"] = ["act_pt_ghost"]
        p.write_text(yaml.safe_dump(doc))

    pack = _broken(tmp_path, mutate)
    scoped = validate(pack, app="console")
    refs = {f.ref for f in scoped.findings}
    # console finding kept, portal action finding filtered out
    assert "act_cs_create_project" in refs
    assert "act_pt_open_wallets" not in refs
    # and it still reports errors for the in-scope app
    assert any(f.severity == ERROR for f in scoped.findings)
