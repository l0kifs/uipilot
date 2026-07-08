"""Read a pack's optional ``.env`` file into a plain dict.

Infrastructure boundary: the only place that reads a pack's ``.env`` from disk.
It returns a plain ``dict[str, str]`` that the application layer merges *under*
the process environment when building a run's
:class:`~uipilot.domain.templating.RuntimeContext`, so env-bound tokens and base
URLs (e.g. credentials, hostnames) can be configured per-project on disk without
exporting shell variables. Values here are **defaults**: a real process (or
explicitly injected) variable of the same name wins.

The format is the conventional ``KEY=VALUE`` subset that dotenv tools accept,
kept dependency-free and tolerant (like the pack loader — a malformed line is
skipped, never raised):

* blank lines and ``#`` comment lines are ignored;
* a leading ``export`` is stripped (``export KEY=VALUE``);
* whitespace around key and value is trimmed;
* a value may be wrapped in single or double quotes — the quotes are removed and
  anything after the closing quote is ignored;
* an *unquoted* value drops a trailing `` # comment`` (space then hash);
* inside double quotes, ``\\n`` / ``\\t`` / ``\\r`` / ``\\"`` / ``\\\\`` escapes
  are expanded (single quotes are literal);
* a line without ``=``, or with an empty key, is skipped.
"""

from __future__ import annotations

from pathlib import Path

ENV_FILENAME = ".env"


def _clean_value(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    quote = value[0]
    if quote in ("'", '"'):
        end = value.find(quote, 1)
        if end != -1:
            inner = value[1:end]
            if quote == '"':
                # Expand backslash escapes. Protect literal ``\\`` first via a
                # sentinel so it is not re-interpreted by the later replaces.
                inner = (
                    inner.replace("\\\\", "\x00")
                    .replace("\\n", "\n")
                    .replace("\\t", "\t")
                    .replace("\\r", "\r")
                    .replace('\\"', '"')
                    .replace("\x00", "\\")
                )
            return inner
        # Unterminated quote — treat the rest literally (below).
    hash_idx = value.find(" #")
    if hash_idx != -1:
        value = value[:hash_idx]
    return value.strip()


def parse_env(text: str) -> dict[str, str]:
    """Parse ``.env`` text into a dict. Pure — no I/O, so trivially testable."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key:
            continue
        out[key] = _clean_value(value)
    return out


def read_env_file(path: str | Path) -> dict[str, str]:
    """Return the parsed ``.env`` at ``path``, or ``{}`` if it does not exist."""
    p = Path(path)
    if not p.is_file():
        return {}
    return parse_env(p.read_text(encoding="utf-8"))
