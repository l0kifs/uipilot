"""Demo pack auth capability adapters.

The engine calls these by name (see ``flowmap.config.yaml``); it never runs them
during emit. Real packs delegate to their existing test-framework helpers rather
than reimplementing auth. These stubs just prove the binding resolves.
"""

from __future__ import annotations


def totp_from_secret(secret: str) -> str:
    """Return a 6-digit TOTP for ``secret`` (stub — a real pack uses pyotp)."""
    raise NotImplementedError("demo stub: wire to your TOTP helper")


def playwright_storage_state(key: str) -> dict:
    """Return a Playwright storageState dict for reuse key ``key`` (stub)."""
    raise NotImplementedError("demo stub: wire to your storageState store")
