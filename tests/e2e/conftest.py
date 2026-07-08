"""Tier marker for every test under tests/e2e/ — no test can silently escape it."""

from __future__ import annotations

from pathlib import Path

import pytest

_HERE = Path(__file__).parent


def pytest_collection_modifyitems(items):
    for item in items:
        if _HERE in item.path.parents:
            item.add_marker(pytest.mark.e2e)
