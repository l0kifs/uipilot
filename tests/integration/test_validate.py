from __future__ import annotations

from pathlib import Path

import yaml

from uipilot.domain.validation import validate
from uipilot.infrastructure.pack_loader import load_pack


def test_demo_pack_is_clean(pack):
    report = validate(pack)
    assert report.errors == 0, [f.as_dict() for f in report.findings if f.severity == "error"]
    assert report.warnings == 0, [f.as_dict() for f in report.findings if f.severity == "warning"]


def _broken_pack(tmp_path: Path, mutate) -> None:
    """Copy the demo pack into tmp_path and apply a mutation callback."""
    import shutil

    src = (
        next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
        / "examples"
        / "demo"
    )
    shutil.copytree(src, tmp_path, dirs_exist_ok=True)
    mutate(tmp_path)


def _codes(pack):
    return {f.code for f in validate(pack).findings}


def test_dangling_element(tmp_path):
    def mutate(root):
        p = root / "data" / "console.app.yaml"
        doc = yaml.safe_load(p.read_text())
        doc["actions"]["act_cs_create_project"]["elements"].append("cs_does_not_exist")
        p.write_text(yaml.safe_dump(doc))

    _broken_pack(tmp_path, mutate)
    assert "E_DANGLING_ELEMENT" in _codes(load_pack(tmp_path))


def test_broken_edge(tmp_path):
    def mutate(root):
        p = root / "data" / "console.app.yaml"
        doc = yaml.safe_load(p.read_text())
        doc["actions"]["act_cs_open_projects"]["next"] = ["act_cs_ghost"]
        p.write_text(yaml.safe_dump(doc))

    _broken_pack(tmp_path, mutate)
    assert "E_BROKEN_EDGE" in _codes(load_pack(tmp_path))


def test_param_undeclared(tmp_path):
    def mutate(root):
        p = root / "data" / "console.app.yaml"
        doc = yaml.safe_load(p.read_text())
        doc["actions"]["act_cs_create_project"]["steps"][2]["value"] = "{{undeclared_thing}}"
        p.write_text(yaml.safe_dump(doc))

    _broken_pack(tmp_path, mutate)
    assert "E_PARAM_UNDECLARED" in _codes(load_pack(tmp_path))


def test_capture_collision(tmp_path):
    def mutate(root):
        # use act_cs_create_project twice without aliases -> capture collision
        p = root / "data" / "flows.yaml"
        doc = yaml.safe_load(p.read_text())
        doc["flows"]["dup"] = {
            "app": "console",
            "path": ["act_cs_create_project", "act_cs_create_project"],
        }
        p.write_text(yaml.safe_dump(doc))

    _broken_pack(tmp_path, mutate)
    assert "E_CAPTURE_COLLISION" in _codes(load_pack(tmp_path))


def test_subflow_cycle(tmp_path):
    def mutate(root):
        p = root / "data" / "flows.yaml"
        doc = yaml.safe_load(p.read_text())
        doc["flows"]["loop_a"] = {"app": "console", "path": [{"use": "loop_b"}]}
        doc["flows"]["loop_b"] = {"app": "console", "path": [{"use": "loop_a"}]}
        p.write_text(yaml.safe_dump(doc))

    _broken_pack(tmp_path, mutate)
    assert "E_SUBFLOW_CYCLE" in _codes(load_pack(tmp_path))


def test_unmet_requires(tmp_path):
    def mutate(root):
        # a flow that reaches a wallet-requiring action with no provider
        p = root / "data" / "flows.yaml"
        doc = yaml.safe_load(p.read_text())
        doc["flows"]["bad_withdraw"] = {
            "app": "portal",
            "path": ["act_pt_sign_in", "act_pt_open_wallet_detail"],
        }
        p.write_text(yaml.safe_dump(doc))

    _broken_pack(tmp_path, mutate)
    assert "W_UNMET_REQUIRES" in _codes(load_pack(tmp_path))


def test_api_call_unbound(tmp_path):
    def mutate(root):
        p = root / "data" / "flows.yaml"
        doc = yaml.safe_load(p.read_text())
        doc["actions"]["api_create_project"]["call"] = "not_a_binding"
        p.write_text(yaml.safe_dump(doc))

    _broken_pack(tmp_path, mutate)
    assert "E_API_CALL_UNBOUND" in _codes(load_pack(tmp_path))


def test_selector_ambiguous(tmp_path):
    def mutate(root):
        p = root / "data" / "console.app.yaml"
        doc = yaml.safe_load(p.read_text())
        # make credential submit identical to project submit
        doc["elements"]["cs_btn_create_credential_submit"]["selector"] = {
            "strategy": "role",
            "role": "button",
            "name": "Create",
            "scope": "dialog",
        }
        p.write_text(yaml.safe_dump(doc))

    _broken_pack(tmp_path, mutate)
    assert "E_SELECTOR_AMBIGUOUS" in _codes(load_pack(tmp_path))
