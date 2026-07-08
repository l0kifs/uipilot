"""Renderers and read-only verification — pure emit over in-memory compiled scripts."""

from __future__ import annotations

import json

from uipilot.domain.compiler import compile_flow
from uipilot.domain.verification import verify_probe
from uipilot.presentation import renderers as emit


def test_emit_json_and_mcp_shapes(pack, ctx):
    s = compile_flow(pack, ctx, "create_project_with_credential")
    as_json = json.loads(emit.to_json(s))
    assert "steps" in as_json and "mcp" not in as_json["steps"][0]
    as_mcp = json.loads(emit.to_playwright_mcp(s))
    assert "mcp" in as_mcp["steps"][0]


def test_emit_pw_test_uses_locators(pack, ctx):
    s = compile_flow(pack, ctx, "create_project_with_credential")
    spec = emit.to_pw_test(s)
    assert "getByRole('button', { name: 'Sign in' })" in spec
    assert "@playwright/test" in spec


def test_emit_pw_pom(pack):
    pom = emit.render_pw_pom(pack, "console")
    assert "class ConsolePage" in pom
    assert "get_by_role" in pom
    assert "DO NOT EDIT" in pom


def test_verify_probe_is_read_only(pack, ctx):
    probe = verify_probe(pack, ctx, flow="create_project_with_credential")
    assert probe["read_only"] is True
    ops = {s["op"] for s in probe["steps"]}
    assert ops <= {"navigate", "snapshot", "expect"}  # no clicks/fills


def test_verify_drive_refuses_gated(pack, ctx):
    probe = verify_probe(pack, ctx, flow="portal_withdrawal_via_ui", drive=True)
    assert probe["refused_gated"]
