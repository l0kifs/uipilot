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


_TIERS = {"unit", "integration", "e2e"}


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items):
    # Each tier dir's conftest tags its own tests; enforce exactly one tier per
    # test so nothing escapes tier selection (a test outside tests/{unit,integration,e2e}/
    # gets no tier and fails here).
    untiered = [
        item.nodeid for item in items if len({m.name for m in item.iter_markers()} & _TIERS) != 1
    ]
    if untiered:
        raise pytest.UsageError(
            "tests must carry exactly one tier marker (unit/integration/e2e); offenders:\n  "
            + "\n  ".join(untiered)
        )
