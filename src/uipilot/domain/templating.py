"""Template resolution and per-run token context — pure domain logic.

No I/O: the environment is *injected* as a plain dict (the application layer
passes ``os.environ``), so this module stays free of process/OS coupling and is
trivially testable.
"""

from __future__ import annotations

import re
from typing import Optional

from uipilot.domain.model import App, Config

_TEMPLATE_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


class RuntimeContext:
    """Resolves env-bound base URLs and pack tokens for a single run.

    Tokens are cached on first access so ``{{prefix}}``/``{{seq}}`` are stable
    across the whole compiled script (one run == one seq), matching the
    "per-run monotonic counter" intent.
    """

    def __init__(
        self,
        config: Config,
        env: Optional[dict] = None,
        counter_start: int = 1,
    ) -> None:
        self.config = config
        self.env = dict(env or {})
        self._counter = counter_start
        self._token_cache: dict[str, Optional[str]] = {}

    def base_url(self, app: App) -> str:
        if app.base_url_env and self.env.get(app.base_url_env):
            return self.env[app.base_url_env]
        return app.base_url_default or ""

    def token(self, key: str) -> Optional[str]:
        if key in self._token_cache:
            return self._token_cache[key]
        tok = self.config.tokens.get(key)
        if tok is None:
            self._token_cache[key] = None
            return None
        if tok.from_ == "env":
            val = self.env.get(tok.name or "", tok.default)
        elif tok.from_ == "counter":
            val = str(self._counter)
            self._counter += 1
        else:
            val = tok.default
        self._token_cache[key] = val
        return val


def iter_template_refs(template: Optional[str]) -> list[str]:
    """Return the raw ``{{...}}`` keys referenced in a template string."""
    if not template:
        return []
    return [m.group(1).strip() for m in _TEMPLATE_RE.finditer(template)]


def resolve_template(
    template: Optional[str],
    values: dict,
    ctx: Optional[RuntimeContext] = None,
) -> tuple[Optional[str], list[str]]:
    """Substitute ``{{key}}`` refs in ``template``.

    Resolution order per key:

    * a dotted key (``captured.x``, ``alias.x``) is a **runtime capture** — left
      as-is for the agent to fill from a prior step's output.
    * an explicit value in ``values`` (params, ``base_url``) wins next.
    * then a pack token via ``ctx``.

    Anything still unresolved is left as ``{{key}}`` and returned in the second
    element so callers can list it under ``params_required``.
    """
    if template is None:
        return None, []
    unresolved: list[str] = []

    def _sub(match: re.Match) -> str:
        key = match.group(1).strip()
        if "." in key:  # runtime capture — resolved by the agent at run time
            return match.group(0)
        if key in values and values[key] is not None:
            return str(values[key])
        if ctx is not None:
            tok = ctx.token(key)
            if tok is not None:
                return str(tok)
        unresolved.append(key)
        return match.group(0)

    return _TEMPLATE_RE.sub(_sub, template), unresolved
