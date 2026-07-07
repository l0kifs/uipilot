from __future__ import annotations

from pathlib import Path

import pytest

from uipilot.domain.templating import RuntimeContext
from uipilot.infrastructure.pack_loader import load_pack

DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo"


@pytest.fixture
def pack():
    return load_pack(DEMO)


@pytest.fixture
def ctx(pack):
    # Deterministic env: no ambient env vars leak into token resolution.
    return RuntimeContext(pack.config, env={"TEST_ENTITY_PREFIX": "demo"})
