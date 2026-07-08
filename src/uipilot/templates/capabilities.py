"""Named auth adapters uipilot invokes by key (declared in flowmap.config.yaml).

Uncomment and wire these to your existing test-framework helpers as needed, then
declare them under `capabilities:` in flowmap.config.yaml. uipilot never runs them
during emit — it only import-checks them (`uipilot capabilities --check`).
"""

from __future__ import annotations


# def totp(secret: str) -> str:
#     """Return a 6-digit TOTP for `secret` (e.g. via pyotp)."""
#     ...


# def storage_state(key: str) -> dict:
#     """Return a Playwright storageState dict for reuse key `key`."""
#     ...
