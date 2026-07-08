"""Reverse index — the change blast radius for an element/action/flow.

``uipilot uses <id>`` answers *"what breaks if I edit this?"* before you touch
it, the payoff of id-indirection (design §8).
"""

from __future__ import annotations

from uipilot.domain.flows import flatten_flow
from uipilot.domain.model import Pack


def _flows_containing_actions(pack: Pack, action_ids: set[str]) -> list[str]:
    hits = []
    for fid, flow in pack.flows.items():
        flat = {aid for aid, _alias in flatten_flow(pack, flow)}
        if flat & action_ids:
            hits.append(fid)
    return sorted(hits)


def uses(pack: Pack, ref: str) -> dict:
    if ref in pack.elements:
        used_by_actions = []
        action_ids: set[str] = set()
        for action in pack.actions.values():
            where = []
            if ref in action.elements:
                where.append("elements")
            if any(s.element == ref for s in action.steps):
                where.append("steps")
            if where:
                used_by_actions.append({"id": action.id, "in": where})
                action_ids.add(action.id)
        flows = _flows_containing_actions(pack, action_ids)
        return {
            "id": ref,
            "kind": "element",
            "used_by_actions": used_by_actions,
            "used_by_flows": flows,
            "impact": f"{len(used_by_actions)} action(s), {len(flows)} flow(s)",
        }

    if ref in pack.actions:
        action = pack.actions[ref]
        flows = _flows_containing_actions(pack, {ref})
        neighbours = {"prev": action.prev, "next": action.next}
        referenced_by = [a.id for a in pack.actions.values() if ref in a.prev or ref in a.next]
        return {
            "id": ref,
            "kind": "action",
            "used_by_flows": flows,
            "neighbours": neighbours,
            "referenced_by_edges": sorted(referenced_by),
            "impact": f"{len(flows)} flow(s), {len(referenced_by)} edge neighbour(s)",
        }

    if ref in pack.flows:
        used_by_flows = []
        for fid, flow in pack.flows.items():
            if any(p.use == ref for p in flow.path):
                used_by_flows.append(fid)
        return {
            "id": ref,
            "kind": "flow",
            "used_by_flows": sorted(used_by_flows),
            "impact": f"{len(used_by_flows)} flow(s) embed this subflow",
        }

    return {"id": ref, "kind": "unknown", "error": f"no element/action/flow named '{ref}'"}
