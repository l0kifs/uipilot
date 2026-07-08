from __future__ import annotations

import pytest

from uipilot.domain.errors import CapabilityError
from uipilot.domain.validation import validate
from uipilot.infrastructure.capabilities import CapabilityRegistry
from uipilot.infrastructure.markdown_importer import import_md, write_seed
from uipilot.infrastructure.pack_loader import load_pack

STRUCTURED_MD = """
# UI Flow Map

```yaml
app:
  id: web
  id_prefix: w
  base_url: { env: WEB_URL, default: "http://localhost:3000" }
elements:
  w_btn_go:
    type: button
    selector: { strategy: role, role: button, name: "Go" }
    purpose: "start"
actions:
  act_w_start:
    app: web
    purpose: "start"
    route: "/"
    elements: [w_btn_go]
    steps:
      - { op: click, element: w_btn_go }
```
"""


def test_import_structured_yaml_fences(tmp_path):
    md = tmp_path / "map.md"
    md.write_text(STRUCTURED_MD)
    result = import_md(md)
    assert result.structured is True
    assert "web" in result.apps
    assert "w_btn_go" in result.apps["web"]["elements"]


def test_import_writes_loadable_pack(tmp_path):
    md = tmp_path / "map.md"
    md.write_text(STRUCTURED_MD)
    result = import_md(md)
    out = tmp_path / "pack"
    write_seed(result, out)
    pack = load_pack(out)  # must load without raising
    assert "act_w_start" in pack.actions
    # structural validation runs (may warn, must not explode)
    validate(pack)


def test_import_heuristic_harvest(tmp_path):
    md = tmp_path / "map.md"
    md.write_text("act_op_do_thing uses op_btn_thing and op_input_thing.")
    result = import_md(md)
    assert result.structured is False
    assert "op" in result.apps
    assert any("btn_thing" in e for e in result.apps["op"]["elements"])


def test_capability_registry_resolves(pack):
    reg = CapabilityRegistry(pack.config, pack.root)
    assert set(reg.keys) == {"totp", "storage_state"}
    # demo capabilities import cleanly (they raise only when *called*)
    assert reg.check_all() == {"totp": None, "storage_state": None}


def test_capability_missing_key_raises(pack):
    reg = CapabilityRegistry(pack.config, pack.root)
    with pytest.raises(CapabilityError):
        reg.get("does_not_exist")
