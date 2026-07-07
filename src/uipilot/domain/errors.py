"""Exception hierarchy for the engine.

Kept deliberately small: the engine either loads a pack successfully or fails
with a `PackError` that names the offending file/id. Everything a *human*
should act on (dangling refs, broken edges, …) is surfaced as structured
`Finding`s by :mod:`uipilot.validate`, not exceptions.
"""

from __future__ import annotations


class UipilotError(Exception):
    """Base class for all engine errors."""


class PackError(UipilotError):
    """A pack could not be loaded or is structurally invalid at load time.

    Distinct from a *lint* finding: a `PackError` means the YAML cannot be
    turned into a model at all (missing file, unparseable YAML, unknown app in
    ``apps:``). Recoverable inconsistencies (a dangling element ref) are
    reported by ``uipilot validate`` instead so the whole model still loads.
    """


class ResolutionError(UipilotError):
    """A template referenced a token/param that could not be resolved and the
    caller asked for strict resolution."""


class CapabilityError(UipilotError):
    """A named capability adapter could not be imported or invoked."""
