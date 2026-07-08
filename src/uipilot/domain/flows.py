"""Flow expansion — the single source of truth for inlining subflows.

A flow ``path`` may contain bare action ids, ``use:`` subflow references, and
aliased invocations. Several domain services need to walk a flow into its
concrete action invocations (the compiler, the linter, the usage index, the
verifier). They all go through here so subflow inlining, aliasing, and the
one-level nesting cap behave identically everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from uipilot.domain.model import Flow, Pack


@dataclass
class Invocation:
    """One concrete action call produced by expanding a flow path."""

    action_id: str
    alias: Optional[str] = None
    params: dict = field(default_factory=dict)
    role: Optional[str] = None


def expand_invocations(
    pack: Pack,
    flow_id: str,
    depth: int = 0,
    alias_ctx: Optional[str] = None,
    seen: Optional[set] = None,
) -> list[Invocation]:
    """Expand a flow into ordered :class:`Invocation`s, inlining subflows.

    Cycle-guarded and capped at one real level of nesting; a recursive ``use:``
    is dropped here (reported separately as ``E_SUBFLOW_CYCLE``).
    """
    seen = seen or set()
    flow = pack.flow(flow_id)
    if flow is None or flow_id in seen or depth > 2:
        return []
    seen = seen | {flow_id}
    out: list[Invocation] = []
    for pstep in flow.path:
        if pstep.action:
            out.append(
                Invocation(pstep.action, pstep.alias or alias_ctx, dict(pstep.params), pstep.role)
            )
        elif pstep.use:
            out += expand_invocations(pack, pstep.use, depth + 1, pstep.alias or alias_ctx, seen)
    return out


def flatten_flow(pack: Pack, flow: Flow) -> list[tuple[str, Optional[str]]]:
    """The ``(action_id, alias)`` view of an expanded flow."""
    return [(inv.action_id, inv.alias) for inv in expand_invocations(pack, flow.id)]
