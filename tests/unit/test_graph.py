from __future__ import annotations

from uipilot.domain.graph import find_path, reachable_actions


def test_find_path_bfs(pack):
    r = find_path(pack, "act_cs_view_dashboard", "act_cs_create_credential")
    assert r.found
    assert r.path[0] == "act_cs_view_dashboard"
    assert r.path[-1] == "act_cs_create_credential"
    # shortest path is monotonic along next-edges
    assert "act_cs_create_project" in r.path


def test_find_path_same_node(pack):
    r = find_path(pack, "act_cs_view_dashboard", "act_cs_view_dashboard")
    assert r.found and r.path == ["act_cs_view_dashboard"]


def test_find_path_api_action_rejected(pack):
    r = find_path(pack, "api_create_project", "act_cs_create_project")
    assert not r.found
    assert "non-UI" in (r.reason or "")


def test_find_path_none_when_unreachable(pack):
    # portal and console graphs are disconnected
    r = find_path(pack, "act_cs_view_dashboard", "act_pt_submit_withdrawal")
    assert not r.found


def test_reachability_covers_all_ui_actions(pack):
    reached = reachable_actions(pack)
    for action in pack.ui_actions():
        assert action.id in reached, f"{action.id} unreachable"
