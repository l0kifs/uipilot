"""Infrastructure-layer tests: loader parse errors + the capability registry.

The loader is deliberately tolerant of *model* inconsistencies (the linter
reports those) but raises :class:`PackError` on genuinely unparseable input.
These tests pin every raise site and the selector-strategy inference, plus the
capability registry's import/binding failure modes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from uipilot.domain.errors import CapabilityError, PackError
from uipilot.domain.model import CapabilitySpec, Config
from uipilot.infrastructure import pack_loader as pl
from uipilot.infrastructure.capabilities import CapabilityRegistry

DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo"


# ---------------------------------------------------------------------------
# _read_yaml
# ---------------------------------------------------------------------------


def test_read_yaml_missing_file(tmp_path):
    with pytest.raises(PackError, match="missing file"):
        pl._read_yaml(tmp_path / "nope.yaml")


def test_read_yaml_non_mapping_top_level(tmp_path):
    p = tmp_path / "list.yaml"
    p.write_text("- a\n- b\n")
    with pytest.raises(PackError, match="mapping at the top level"):
        pl._read_yaml(p)


def test_read_yaml_empty_file_is_empty_dict(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    assert pl._read_yaml(p) == {}


# ---------------------------------------------------------------------------
# _parse_selector — strategy inference + errors
# ---------------------------------------------------------------------------


def test_parse_selector_infers_strategy():
    assert pl._parse_selector({"role": "button"}, where="x").strategy == "role"
    assert pl._parse_selector({"css": ".x"}, where="x").strategy == "css"
    assert pl._parse_selector({"text": "Hi"}, where="x").strategy == "text"
    assert pl._parse_selector({"label": "L"}, where="x").strategy == "label"
    assert pl._parse_selector({"testid": "t"}, where="x").strategy == "testid"


def test_parse_selector_errors():
    with pytest.raises(PackError, match="must be a mapping"):
        pl._parse_selector("nope", where="x")
    with pytest.raises(PackError, match="needs a strategy"):
        pl._parse_selector({"purpose": "no locator"}, where="x")


# ---------------------------------------------------------------------------
# _parse_param / _parse_step / _parse_capture / _parse_path_step
# ---------------------------------------------------------------------------


def test_parse_param_requires_key():
    with pytest.raises(PackError, match="needs a 'key'"):
        pl._parse_param({"type": "string"}, where="x")


def test_parse_step_requires_op_and_normalises_wait_for():
    with pytest.raises(PackError, match="needs an 'op'"):
        pl._parse_step({"element": "e"}, where="x")
    step = pl._parse_step({"op": "wait_for", "wait_for": "Loaded", "extra": 1}, where="x")
    assert step.wait_for == {"text": "Loaded"}
    assert step.args == {"extra": 1}  # unknown keys pooled into args


def test_parse_capture_requires_key():
    with pytest.raises(PackError, match="needs a 'key'"):
        pl._parse_capture({"from": "url"}, where="x")


def test_parse_path_step_variants_and_errors():
    assert pl._parse_path_step("act_x", where="f").action == "act_x"
    use = pl._parse_path_step({"use": "sub", "as": "al", "args": {"k": "v"}}, where="f")
    assert use.use == "sub" and use.alias == "al" and use.params == {"k": "v"}
    act = pl._parse_path_step(
        {"action": "a", "role": "crosscheck", "params": {"p": 1}, "args": {"q": 2}}, where="f"
    )
    assert act.role == "crosscheck" and act.params == {"p": 1, "q": 2}
    with pytest.raises(PackError, match="string or mapping"):
        pl._parse_path_step(123, where="f")
    with pytest.raises(PackError, match="needs 'action' or 'use'"):
        pl._parse_path_step({"foo": "bar"}, where="f")


def test_parse_action_and_flow_type_errors():
    with pytest.raises(PackError, match="expected a mapping"):
        pl._parse_action("a", "notdict", default_app="x")
    with pytest.raises(PackError, match="expected a mapping"):
        pl._parse_flow("f", "notdict")


# ---------------------------------------------------------------------------
# _parse_app_header / _parse_config
# ---------------------------------------------------------------------------


def test_parse_app_header_requires_id():
    with pytest.raises(PackError, match="needs an 'id'"):
        pl._parse_app_header({"id_prefix": "x"})
    app = pl._parse_app_header(
        {"id": "web", "auth": {"entry_flow": "sign_in", "storage_state_key": "web"}}
    )
    assert app.auth.entry_flow == "sign_in"


def test_parse_config_requires_apps_and_capability_impl():
    with pytest.raises(PackError, match="needs an 'apps' list"):
        pl._parse_config({}, where="cfg")
    with pytest.raises(PackError, match="needs an 'impl'"):
        pl._parse_config({"apps": ["a"], "capabilities": {"totp": {}}}, where="cfg")
    cfg = pl._parse_config({"apps": ["a"], "tokens": {"seq": {"from": "counter"}}}, where="cfg")
    assert cfg.tokens["seq"].from_ == "counter"


# ---------------------------------------------------------------------------
# load_pack — directory-level errors
# ---------------------------------------------------------------------------


def _copy_demo(tmp_path):
    import shutil

    shutil.copytree(DEMO, tmp_path, dirs_exist_ok=True)
    return tmp_path


def test_load_pack_missing_app_header(tmp_path):
    root = _copy_demo(tmp_path)
    p = root / "data" / "console.app.yaml"
    doc = yaml.safe_load(p.read_text())
    del doc["app"]
    p.write_text(yaml.safe_dump(doc))
    with pytest.raises(PackError, match="missing 'app:' header"):
        pl.load_pack(root)


def test_load_pack_app_id_mismatch(tmp_path):
    root = _copy_demo(tmp_path)
    p = root / "data" / "console.app.yaml"
    doc = yaml.safe_load(p.read_text())
    doc["app"]["id"] = "renamed"
    p.write_text(yaml.safe_dump(doc))
    with pytest.raises(PackError, match="does not match filename"):
        pl.load_pack(root)


def test_load_pack_without_flows_file(tmp_path):
    """A pack with no flows.yaml still loads (flows are optional)."""
    root = _copy_demo(tmp_path)
    (root / "data" / "flows.yaml").unlink()
    pack = pl.load_pack(root)
    assert pack.flows == {}
    assert pack.apps  # apps/elements/actions still present


# ---------------------------------------------------------------------------
# CapabilityRegistry
# ---------------------------------------------------------------------------


def _reg(impls: dict, root=None):
    caps = {k: CapabilitySpec(key=k, impl=v) for k, v in impls.items()}
    return CapabilityRegistry(Config(pack="p", apps=[], capabilities=caps), root)


def test_capability_spec_and_missing_key():
    reg = _reg({"totp": "capabilities:totp_from_secret"}, root=DEMO)
    assert reg.spec("totp") == "capabilities:totp_from_secret"
    assert reg.spec("ghost") is None
    with pytest.raises(CapabilityError, match="no capability named"):
        reg.get("ghost")


def test_capability_resolves_and_caches():
    reg = _reg({"totp": "capabilities:totp_from_secret"}, root=DEMO)
    fn = reg.get("totp")
    assert callable(fn)
    assert reg.get("totp") is fn  # cached
    assert reg.check("totp") is None


def test_capability_binding_errors():
    reg = _reg(
        {
            "no_colon": "justmodule",
            "bad_module": "no_such_module_xyz:fn",
            "bad_attr": "capabilities:missing_fn",
            "not_callable": "capabilities:__doc__",
        },
        root=DEMO,
    )
    checks = reg.check_all()
    assert "must be 'module.path:function'" in checks["no_colon"]
    assert "cannot import" in checks["bad_module"]
    assert "has no attribute" in checks["bad_attr"]
    assert "not callable" in checks["not_callable"]


def test_capability_registry_without_pack_root():
    # pack_root=None exercises the no-op _pack_on_path branch; the stdlib module
    # `json` imports cleanly and `dumps` is callable.
    reg = _reg({"j": "json:dumps"}, root=None)
    assert callable(reg.get("j"))
