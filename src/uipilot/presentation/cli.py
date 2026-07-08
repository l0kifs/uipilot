"""``uipilot`` — the engine CLI (Typer + Rich).

Presentation layer: it parses args, calls the application use cases, and formats
the returned domain objects as JSON / Rich tables / generated source. It talks
to :mod:`uipilot.application.service` and never reaches into infrastructure or
domain services directly (it references domain *types* only for shaping).

Global flags: ``--pack <path>`` (a pack dir; defaults to $UIPILOT_PACK, else a
``.uipilot/`` pack in the cwd, else the bundled example) and ``--format
json|table|md`` (default ``json`` — agent-consumable).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from uipilot.application import service
from uipilot.application.service import PackContext
from uipilot.domain.errors import PackError, UipilotError
from uipilot.infrastructure.pack_loader import PACK_SUBDIR
from uipilot.presentation import renderers

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Compile web-UI flows into Playwright-MCP scripts for agents.",
)
show_app = typer.Typer(no_args_is_help=True, help="Show a single action or element.")
app.add_typer(show_app, name="show")

console = Console()
err_console = Console(stderr=True)

_BUNDLED_EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "demo"


@dataclass
class State:
    pack_path: Optional[str]
    fmt: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_pack() -> Optional[str]:
    env = os.environ.get("UIPILOT_PACK")
    if env:
        return env
    pack = Path.cwd() / PACK_SUBDIR
    if (pack / "flowmap.config.yaml").exists():
        return str(pack)
    if (_BUNDLED_EXAMPLE / "flowmap.config.yaml").exists():
        return str(_BUNDLED_EXAMPLE)
    return None


def _load(ctx: typer.Context) -> PackContext:
    state: State = ctx.obj
    pack_path = state.pack_path or _default_pack()
    if not pack_path:
        err_console.print(
            "[red]no pack found[/red]: pass --pack, set $UIPILOT_PACK, "
            "or run `uipilot init` to scaffold a .uipilot/ pack"
        )
        raise typer.Exit(2)
    try:
        return service.open_pack(pack_path)
    except PackError as exc:
        err_console.print(f"[red]pack error[/red]: {exc}")
        raise typer.Exit(2) from None


def _emit(ctx: typer.Context, obj: dict, table_fn=None) -> None:
    state: State = ctx.obj
    if state.fmt == "table" and table_fn is not None:
        table_fn(obj)
    elif state.fmt == "md":
        console.print("```json")
        console.print(json.dumps(obj, indent=2))
        console.print("```")
    else:
        print(json.dumps(obj, indent=2))


def _short(text: str, width: int = 48) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


def _step_dict(s) -> dict:
    out = {"op": s.op}
    for k in ("element", "value", "scope"):
        v = getattr(s, k)
        if v is not None:
            out[k] = v
    if s.wait_for:
        out["wait_for"] = s.wait_for
    if s.optional:
        out["optional"] = True
    return out


# ---------------------------------------------------------------------------
# Root callback
# ---------------------------------------------------------------------------


@app.callback()
def main(
    ctx: typer.Context,
    pack: Optional[str] = typer.Option(None, "--pack", help="Pack directory."),
    fmt: str = typer.Option("json", "--format", help="json | table | md"),
) -> None:
    ctx.obj = State(pack_path=pack, fmt=fmt)


# ---------------------------------------------------------------------------
# apps
# ---------------------------------------------------------------------------


@app.command()
def apps(ctx: typer.Context) -> None:
    """List apps, base URLs, and auth entry flows."""
    pctx = _load(ctx)
    rows = []
    for a in pctx.pack.apps.values():
        rows.append(
            {
                "id": a.id,
                "id_prefix": a.id_prefix,
                "base_url": pctx.runtime.base_url(a),
                "auth_entry_flow": a.auth.entry_flow if a.auth else None,
                "storage_state_key": a.auth.storage_state_key if a.auth else None,
            }
        )
    payload = {"count": len(rows), "apps": rows}

    def _table(_):
        t = Table(title="apps")
        for col in ("id", "prefix", "base_url", "auth entry flow"):
            t.add_column(col)
        for r in rows:
            t.add_row(r["id"], r["id_prefix"], r["base_url"] or "—", r["auth_entry_flow"] or "—")
        console.print(t)

    _emit(ctx, payload, _table)


# ---------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------


@app.command()
def actions(
    ctx: typer.Context,
    app_id: Optional[str] = typer.Option(None, "--app"),
    section: Optional[str] = typer.Option(None, "--section"),
    risk: Optional[str] = typer.Option(None, "--risk"),
    grep: Optional[str] = typer.Option(None, "--grep"),
    transport: Optional[str] = typer.Option(None, "--transport", help="ui | api"),
) -> None:
    """List / filter actions (graph overview)."""
    pctx = _load(ctx)
    found = service.filter_actions(
        pctx, app=app_id, section=section, risk=risk, grep=grep, transport=transport
    )
    result = [
        {
            "id": a.id,
            "transport": a.transport,
            "purpose": a.purpose,
            "route": a.route,
            "risk": a.risk,
            "prev": a.prev,
            "next": a.next,
            "param_keys": [p.key for p in a.params],
        }
        for a in found
    ]
    payload = {"app": app_id, "count": len(result), "actions": result}

    def _table(_):
        t = Table(title="actions")
        for col in ("id", "t", "risk", "route", "purpose", "next"):
            t.add_column(col)
        for a in found:
            t.add_row(
                a.id,
                a.transport[0],
                a.risk,
                a.route or "—",
                _short(a.purpose),
                ",".join(a.next) or "—",
            )
        console.print(t)

    _emit(ctx, payload, _table)


# ---------------------------------------------------------------------------
# elements
# ---------------------------------------------------------------------------


@app.command()
def elements(
    ctx: typer.Context,
    app_id: Optional[str] = typer.Option(None, "--app"),
    action: Optional[str] = typer.Option(None, "--action"),
    section: Optional[str] = typer.Option(None, "--section"),
    grep: Optional[str] = typer.Option(None, "--grep"),
) -> None:
    """List / filter elements with resolved selectors."""
    pctx = _load(ctx)
    try:
        found = service.filter_elements(pctx, app=app_id, action=action, section=section, grep=grep)
    except KeyError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from None
    result = [
        {
            "id": e.id,
            "type": e.type,
            "section": e.section,
            "selector": e.selector.as_dict(),
            "locator": e.selector.to_locator(),
            "purpose": e.purpose,
        }
        for e in found
    ]
    payload = {"action": action, "count": len(result), "elements": result}

    def _table(_):
        t = Table(title="elements")
        for col in ("id", "type", "locator", "purpose"):
            t.add_column(col)
        for e in found:
            t.add_row(e.id, e.type, _short(e.selector.to_locator(), 40), _short(e.purpose or ""))
        console.print(t)

    _emit(ctx, payload, _table)


# ---------------------------------------------------------------------------
# show action / show element
# ---------------------------------------------------------------------------


@show_app.command("action")
def show_action(ctx: typer.Context, action_id: str) -> None:
    """Full action detail: selectors resolved inline + step recipe."""
    pctx = _load(ctx)
    a = pctx.pack.action(action_id)
    if a is None:
        err_console.print(f"[red]no action[/red] '{action_id}'")
        raise typer.Exit(2)
    elems = []
    for eid in a.elements:
        e = pctx.pack.element(eid)
        if e:
            elems.append(
                {
                    "id": e.id,
                    "selector": e.selector.as_dict(),
                    "locator": e.selector.to_locator(),
                    "purpose": e.purpose,
                }
            )
    payload = {
        "id": a.id,
        "app": a.app,
        "transport": a.transport,
        "route": a.route,
        "purpose": a.purpose,
        "risk": a.risk,
        "call": a.call,
        "role": a.role,
        "elements": elems,
        "params": [
            {
                "key": p.key,
                "type": p.type,
                "required": p.required,
                "default": None if p.is_secret else p.default,
            }
            for p in a.params
        ],
        "steps": [_step_dict(s) for s in a.steps],
        "captures": [{"key": c.key, "from": c.from_, "pattern": c.pattern} for c in a.captures],
        "prev": a.prev,
        "next": a.next,
        "requires": a.requires,
        "provides": a.provides,
    }
    _emit(ctx, payload)


@show_app.command("element")
def show_element(ctx: typer.Context, element_id: str) -> None:
    """Single element detail."""
    pctx = _load(ctx)
    e = pctx.pack.element(element_id)
    if e is None:
        err_console.print(f"[red]no element[/red] '{element_id}'")
        raise typer.Exit(2)
    payload = {
        "id": e.id,
        "app": e.app,
        "type": e.type,
        "section": e.section,
        "selector": e.selector.as_dict(),
        "locator": e.selector.to_locator(),
        "purpose": e.purpose,
    }
    _emit(ctx, payload)


# ---------------------------------------------------------------------------
# uses
# ---------------------------------------------------------------------------


@app.command()
def uses(ctx: typer.Context, ref: str) -> None:
    """Reverse index — everything referencing an element/action/flow."""
    pctx = _load(ctx)
    payload = service.uses(pctx, ref)
    if payload.get("kind") == "unknown":
        err_console.print(f"[red]{payload['error']}[/red]")
        raise typer.Exit(2)
    _emit(ctx, payload)


# ---------------------------------------------------------------------------
# flows / flow
# ---------------------------------------------------------------------------


@app.command()
def flows(ctx: typer.Context) -> None:
    """List named flows."""
    pctx = _load(ctx)
    rows = [
        {"id": f.id, "app": f.app, "description": f.description, "steps": len(f.path)}
        for f in pctx.pack.flows.values()
    ]
    rows.sort(key=lambda r: r["id"])
    payload = {"count": len(rows), "flows": rows}

    def _table(_):
        t = Table(title="flows")
        for col in ("id", "app", "steps", "description"):
            t.add_column(col)
        for f in sorted(pctx.pack.flows.values(), key=lambda fl: fl.id):
            t.add_row(f.id, f.app or "—", str(len(f.path)), _short(f.description))
        console.print(t)

    _emit(ctx, payload, _table)


@app.command()
def flow(
    ctx: typer.Context,
    name: str,
    params_only: bool = typer.Option(
        False, "--params", help="print only the aggregated param manifest (flow + every action)"
    ),
) -> None:
    """Show a named flow (action path + params)."""
    pctx = _load(ctx)
    f = pctx.pack.flow(name)
    if f is None:
        err_console.print(f"[red]no flow[/red] '{name}'")
        raise typer.Exit(2)
    if params_only:
        manifest = service.flow_param_manifest(pctx, name)
        _emit(
            ctx,
            {
                "flow": name,
                "required": [p["key"] for p in manifest if p["required"]],
                "params": manifest,
            },
        )
        return
    path = []
    for p in f.path:
        entry = {}
        if p.action:
            entry["action"] = p.action
        if p.use:
            entry["use"] = p.use
        if p.alias:
            entry["as"] = p.alias
        if p.params:
            entry["params"] = p.params
        path.append(entry)
    payload = {
        "id": f.id,
        "app": f.app,
        "description": f.description,
        "guard": f.guard,
        "path": path,
        "params": [
            {
                "key": p.key,
                "type": p.type,
                "required": p.required,
                "default": None if p.is_secret else p.default,
            }
            for p in f.params
        ],
    }
    _emit(ctx, payload)


# ---------------------------------------------------------------------------
# path
# ---------------------------------------------------------------------------


@app.command()
def path(
    ctx: typer.Context,
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    max_depth: int = typer.Option(25, "--max-depth"),
) -> None:
    """Compute a path through the flow graph (BFS over next-edges)."""
    pctx = _load(ctx)
    _emit(ctx, service.route(pctx, from_, to, max_depth=max_depth))


# ---------------------------------------------------------------------------
# script
# ---------------------------------------------------------------------------


@app.command()
def script(
    ctx: typer.Context,
    flow_name: Optional[str] = typer.Option(None, "--flow"),
    from_: Optional[str] = typer.Option(None, "--from"),
    to: Optional[str] = typer.Option(None, "--to"),
    actions_csv: Optional[str] = typer.Option(None, "--actions", help="a,b,c"),
    params_file: Optional[str] = typer.Option(None, "--params"),
    set_: list[str] = typer.Option(None, "--set", help="key=value (repeatable)"),
    skip_auth: bool = typer.Option(False, "--skip-auth"),
    batch: bool = typer.Option(False, "--batch"),
    refuse_destructive: bool = typer.Option(False, "--refuse-destructive"),
    fmt: str = typer.Option(
        "playwright-mcp", "--format", help="playwright-mcp | steps | json | pw-test | human"
    ),
) -> None:
    """Emit an executable Playwright-MCP script for a flow / path / actions."""
    pctx = _load(ctx)
    overrides = _collect_overrides(params_file, set_)
    ids = [x.strip() for x in actions_csv.split(",") if x.strip()] if actions_csv else None
    try:
        compiled = service.compile_script(
            pctx,
            flow=flow_name,
            src=from_,
            dst=to,
            actions=ids,
            overrides=overrides,
            skip_auth=skip_auth,
            batch=batch,
            refuse_destructive=refuse_destructive,
        )
    except ValueError:
        err_console.print("[red]script needs[/red] --flow, --path (--from/--to), or --actions")
        raise typer.Exit(2) from None
    except (KeyError, UipilotError) as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from None

    if fmt == "steps":
        print(renderers.to_steps(compiled))
    elif fmt == "json":
        print(renderers.to_json(compiled))
    elif fmt == "pw-test":
        print(renderers.to_pw_test(compiled))
    elif fmt == "human":
        print(renderers.to_human(compiled))
    else:
        print(renderers.to_playwright_mcp(compiled))


def _collect_overrides(params_file: Optional[str], set_: Optional[list]) -> dict:
    overrides: dict = {}
    if params_file:
        overrides.update(json.loads(Path(params_file).read_text(encoding="utf-8")))
    for item in set_ or []:
        if "=" not in item:
            raise typer.BadParameter(f"--set expects key=value, got '{item}'")
        k, v = item.split("=", 1)
        overrides[k] = v
    return overrides


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@app.command()
def validate(ctx: typer.Context, app_id: Optional[str] = typer.Option(None, "--app")) -> None:
    """Lint the model statically (dangling refs, broken edges, unreachable…)."""
    pctx = _load(ctx)
    report = service.validate_pack(pctx, app=app_id)

    def _table(_):
        t = Table(title=f"validate: {report.errors} error(s), {report.warnings} warning(s)")
        for col in ("severity", "code", "ref", "message"):
            t.add_column(col)
        for f in report.findings:
            colour = "red" if f.severity == "error" else "yellow"
            t.add_row(f"[{colour}]{f.severity}[/{colour}]", f.code, f.ref, f.message)
        console.print(t)

    _emit(ctx, report.as_dict(), _table)
    if not report.ok:
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


@app.command()
def verify(
    ctx: typer.Context,
    flow_name: Optional[str] = typer.Option(None, "--flow"),
    app_id: Optional[str] = typer.Option(None, "--app"),
    action: Optional[str] = typer.Option(None, "--action"),
    drive: bool = typer.Option(False, "--drive", help="walk the full flow (opt-in)"),
    allow_gated: bool = typer.Option(
        False, "--allow-gated", help="include risk.gated steps in --drive"
    ),
) -> None:
    """Emit a read-only probe script to detect live drift against the running app."""
    pctx = _load(ctx)
    try:
        payload = service.verify(
            pctx, flow=flow_name, app=app_id, action=action, drive=drive, allow_gated=allow_gated
        )
    except (KeyError, ValueError) as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from None
    _emit(ctx, payload)


# ---------------------------------------------------------------------------
# emit (POM / pw-test)
# ---------------------------------------------------------------------------


@app.command()
def emit(
    ctx: typer.Context,
    fmt: str = typer.Option("pw-pom", "--format", help="pw-pom | pw-test"),
    app_id: Optional[str] = typer.Option(None, "--app"),
    flow_name: Optional[str] = typer.Option(None, "--flow"),
) -> None:
    """Emit build artifacts: Python POM classes (pw-pom) or a pw-test spec."""
    pctx = _load(ctx)
    if fmt == "pw-pom":
        print(renderers.render_pw_pom(pctx.pack, app_id))
    elif fmt == "pw-test":
        if not flow_name:
            err_console.print("[red]--format pw-test needs --flow[/red]")
            raise typer.Exit(2)
        compiled = service.compile_script(pctx, flow=flow_name)
        print(renderers.to_pw_test(compiled))
    else:
        err_console.print(f"[red]unknown emit format[/red] '{fmt}'")
        raise typer.Exit(2)


# ---------------------------------------------------------------------------
# capabilities
# ---------------------------------------------------------------------------


@app.command()
def capabilities(
    ctx: typer.Context,
    check: bool = typer.Option(
        False, "--check", help="import each adapter and report binding errors"
    ),
) -> None:
    """List the pack's named capability adapters."""
    pctx = _load(ctx)
    rows = service.list_capabilities(pctx, check=check)
    _emit(ctx, {"count": len(rows), "capabilities": rows})


# ---------------------------------------------------------------------------
# import-md
# ---------------------------------------------------------------------------


@app.command()
def init(
    directory: str = typer.Argument(".", help="project directory to scaffold"),
    agent: list[str] = typer.Option(
        ["claude"],
        "--agent",
        help="claude | agents (repeatable; defaults to claude only, add --agent agents for AGENTS.md)",
    ),
    force: bool = typer.Option(False, "--force", help="overwrite existing pack files"),
) -> None:
    """Scaffold a pack + agent instructions so an agent can use uipilot here."""
    result = service.init_project(directory, agents=agent, force=force)
    console.print(f"[green]✓[/green] uipilot ready in [bold]{result['pack']}[/bold]")
    for rel in result["created"]:
        console.print(f"  [green]created[/green]  {rel}")
    for rel in result["updated"]:
        console.print(f"  [yellow]updated[/yellow]  {rel}")
    for rel in result["skipped"]:
        console.print(f"  [dim]skipped (exists)[/dim]  {rel}")
    console.print("\n[bold]Next:[/bold]")
    console.print(
        "  1. Edit .uipilot/flowmap.config.yaml + .uipilot/data/app.app.yaml: "
        "your app id and base_url."
    )
    console.print("  2. Ask your agent to map and run a flow — it fills the pack for you.")
    console.print("  3. uipilot validate   # check the map is self-consistent")


@app.command("import-md")
def import_md_cmd(
    ctx: typer.Context,
    md_file: str = typer.Argument(...),
    out: str = typer.Option(..., "--out", help="pack directory to seed"),
) -> None:
    """One-time: parse a retired UI_FLOW_MAP.md into seed pack YAML."""
    print(json.dumps(service.import_markdown(md_file, out), indent=2))


if __name__ == "__main__":  # pragma: no cover
    app()
