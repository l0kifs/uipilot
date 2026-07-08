"""Pathfinding over the UI flow graph.

Only **UI** actions are nodes: API actions carry no ``prev``/``next`` and are
excluded from navigation (design §9.3). Edges are the ``next`` lists; ``prev``
mirrors them. ``path`` is a BFS (shortest hop count) from one action to another.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

from uipilot.domain.model import Pack


@dataclass
class PathResult:
    found: bool
    path: list[str]
    length: int
    reason: Optional[str] = None


def _adjacency(pack: Pack) -> dict[str, list[str]]:
    """UI-only successor map, using ``next`` and the mirror of ``prev``."""
    adj: dict[str, set[str]] = {a.id: set() for a in pack.ui_actions()}
    for action in pack.ui_actions():
        for nxt in action.next:
            if nxt in adj:
                adj[action.id].add(nxt)
        # ``prev`` is authoritative in reverse — treat as an incoming edge.
        for prv in action.prev:
            if prv in adj:
                adj[prv].add(action.id)
    return {k: sorted(v) for k, v in adj.items()}


def find_path(
    pack: Pack,
    src: str,
    dst: str,
    max_depth: int = 25,
) -> PathResult:
    """Shortest ``next``-edge path from ``src`` to ``dst`` (inclusive)."""
    if src not in pack.actions or pack.actions[src].is_api:
        return PathResult(False, [], 0, reason=f"unknown or non-UI source action '{src}'")
    if dst not in pack.actions or pack.actions[dst].is_api:
        return PathResult(False, [], 0, reason=f"unknown or non-UI target action '{dst}'")
    if src == dst:
        return PathResult(True, [src], 1)

    adj = _adjacency(pack)
    # BFS carrying the path; depth is the number of nodes on the path.
    queue: deque[list[str]] = deque([[src]])
    seen = {src}
    while queue:
        path = queue.popleft()
        if len(path) > max_depth:
            continue
        for nxt in adj.get(path[-1], []):
            if nxt == dst:
                full = [*path, nxt]
                return PathResult(True, full, len(full))
            if nxt not in seen:
                seen.add(nxt)
                queue.append([*path, nxt])
    return PathResult(False, [], 0, reason="no next-edge path within max-depth")


def _entry_action_ids(pack: Pack) -> set[str]:
    """Actions that begin an auth entry flow (expanded one level)."""
    roots: set[str] = set()
    for app in pack.apps.values():
        if not app.auth or not app.auth.entry_flow:
            continue
        flow = pack.flow(app.auth.entry_flow)
        if not flow:
            continue
        for pstep in flow.path:
            if pstep.action and pstep.action in pack.actions:
                roots.add(pstep.action)
                break  # only the first action is the true entry point
            if pstep.use:
                sub = pack.flow(pstep.use)
                if sub and sub.path and sub.path[0].action:
                    roots.add(sub.path[0].action)
                break
    return roots


def reachable_actions(pack: Pack) -> set[str]:
    """UI actions reachable from an auth entry flow or from a ``prev``-less root.

    Used by ``validate`` to flag ``W_UNREACHABLE`` orphans.
    """
    adj = _adjacency(pack)
    roots = _entry_action_ids(pack)
    # Also treat any UI action with no incoming edge as a root (top of a flow).
    has_incoming: set[str] = set()
    for succs in adj.values():
        has_incoming.update(succs)
    for action in pack.ui_actions():
        if action.id not in has_incoming:
            roots.add(action.id)

    seen: set[str] = set()
    stack = list(roots)
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adj.get(node, []))
    return seen
