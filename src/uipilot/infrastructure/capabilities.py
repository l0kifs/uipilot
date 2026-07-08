"""Named capability adapters.

Capabilities are the one place the *pack* hands executable Python to the engine:
a TOTP generator, a Playwright ``storageState`` reader, a token provider. The
engine never *runs* them during emit (it is emit-only); it only needs to (a)
list them and (b) prove they import, so ``validate`` can flag a broken binding.

An impl is written ``module.path:function``. The pack root is placed on
``sys.path`` while resolving, so ``framework.ui_flow.capabilities:totp`` resolves
against the pack's own source tree.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from uipilot.domain.errors import CapabilityError
from uipilot.domain.model import Config


@contextmanager
def _pack_on_path(pack_root: Optional[Path]):
    if pack_root is None:
        yield
        return
    added = str(pack_root)
    inserted = added not in sys.path
    if inserted:
        sys.path.insert(0, added)
    try:
        yield
    finally:
        if inserted:
            try:
                sys.path.remove(added)
            except ValueError:  # pragma: no cover
                pass


def _import_impl(impl: str, pack_root: Optional[Path]) -> Callable:
    if ":" not in impl:
        raise CapabilityError(f"capability impl '{impl}' must be 'module.path:function'")
    module_name, _, func_name = impl.partition(":")
    with _pack_on_path(pack_root):
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            raise CapabilityError(f"cannot import '{module_name}': {exc}") from exc
        try:
            func = getattr(module, func_name)
        except AttributeError as exc:
            raise CapabilityError(f"'{module_name}' has no attribute '{func_name}'") from exc
    if not callable(func):
        raise CapabilityError(f"capability '{impl}' is not callable")
    return func


class CapabilityRegistry:
    """Lazy registry over the pack's declared capabilities."""

    def __init__(self, config: Config, pack_root: Optional[Path] = None) -> None:
        self._config = config
        self._pack_root = pack_root
        self._cache: dict[str, Callable] = {}

    @property
    def keys(self) -> list[str]:
        return sorted(self._config.capabilities)

    def spec(self, key: str) -> Optional[str]:
        cap = self._config.capabilities.get(key)
        return cap.impl if cap else None

    def get(self, key: str) -> Callable:
        """Import and return the adapter callable for ``key``."""
        if key in self._cache:
            return self._cache[key]
        cap = self._config.capabilities.get(key)
        if cap is None:
            raise CapabilityError(f"no capability named '{key}'")
        func = _import_impl(cap.impl, self._pack_root)
        self._cache[key] = func
        return func

    def check(self, key: str) -> Optional[str]:
        """Return an error string if the binding is broken, else ``None``."""
        try:
            self.get(key)
            return None
        except CapabilityError as exc:
            return str(exc)

    def check_all(self) -> dict[str, Optional[str]]:
        return {key: self.check(key) for key in self.keys}
