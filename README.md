# uipilot

**App-agnostic engine that models a web UI as a graph and compiles flows into
Playwright-MCP-executable scripts for agents.**

An agent driving a web UI live pays, per element: snapshot → reason about intent
→ find the ref → act. `uipilot` turns that into a lookup. You describe your app's
elements, actions, and flows once as structured YAML (a **pack**); the engine
queries that graph and emits a step-by-step Playwright-MCP script with selectors
pre-resolved and page snapshots inserted only where the DOM actually changes.

The engine ships **no domain vocabulary** — no "login", "cart", "tenant". It
knows only generic concepts (**app, element, action, flow, step, param,
capture, capability**). Everything project-specific lives in a pack, so porting
to a new web app means authoring a new pack, not touching the engine.

> **The engine executes nothing.** Every command *emits structured data*; the
> agent owns the browser and runs it. That keeps `uipilot` safe to point at
> money-moving flows.

---

## Install & set up in your project

```bash
uv tool install uipilot          # install the CLI globally
cd your-project
uipilot init                     # scaffold a pack + agent instructions here
```

`uipilot init` writes a minimal, valid pack skeleton under `.uipilot/`
(`.uipilot/flowmap.config.yaml`, `.uipilot/data/`, `.uipilot/capabilities.py`)
plus an agent instruction file at the project root — a Claude Code skill
(`.claude/skills/uipilot/SKILL.md`) and/or an `AGENTS.md` section (`--agent
claude|agents`, repeatable). Then just **ask your agent to run a flow**: it
explores the app, fills the pack, and drives it for you. Re-running `init`
refreshes the skill but never clobbers a pack you've started (use `--force` to
overwrite).

Because `init` scaffolds a `.uipilot/` pack in the cwd, every later `uipilot …`
call finds it with **no `--pack` flag** (resolution order: `$UIPILOT_PACK` → a
`.uipilot/` pack in the cwd → the bundled `examples/demo` pack).

### From source

```bash
uv sync                                    # creates .venv, installs from uv.lock
uv run uipilot --pack examples/demo apps
```

Built with the `uv_build` backend; dependencies are locked in `uv.lock`.

---

## The 60-second tour

```bash
# what apps/flows exist?
uipilot --pack examples/demo --format table apps
uipilot --pack examples/demo flows

# compile a flow into an executable Playwright-MCP script
uipilot --pack examples/demo script --flow create_project_with_credential

# find a route through the UI graph
uipilot --pack examples/demo path --from act_cs_view_dashboard --to act_cs_create_credential

# what breaks if I edit this button? (change blast radius)
uipilot --pack examples/demo uses cs_btn_create_project_submit

# is the map self-consistent? (CI gate)
uipilot --pack examples/demo validate

# does the map still match the running app? (read-only live probe)
uipilot --pack examples/demo verify --flow create_project_with_credential
```

---

## Pack layout

```
.uipilot/                     # the pack dir (scaffolded by `uipilot init`)
├── flowmap.config.yaml       # binds apps, tokens, risk taxonomy, capabilities
├── capabilities.py           # (optional) named auth adapters the engine calls by key
└── data/
    ├── <app>.app.yaml        # one per app: app header + elements + actions
    └── flows.yaml            # named multi-app flows (+ shared/API actions)
```

* **Element** — a node with a structured selector (`role(name)` > `label` >
  `text` > `css`) and a purpose. Never a raw locator string, so it re-emits to a
  Playwright-MCP element description *or* a `@playwright/test` locator.
* **Action** — the graph proper. A UI action carries a `route`, an ordered
  `steps` recipe, `prev`/`next` edges, `params`, and `captures`. An **API
  action** (`transport: api`) binds to an existing test-framework factory via
  `call:` for fast provisioning or backend cross-checks — it has no `prev`/`next`
  and is excluded from pathfinding.
* **Flow** — an ordered `path` of action ids. Entries can be a bare id, a
  subflow (`use:`), or an aliased repeat (`{action, as, params}`). Reuse is
  layered L1–L4 (shared actions → subflows → aliased invocations → guards).
* **Capture** — a value one action produces (`from: url|element|response|…`)
  that later steps consume as `{{captured.x}}` / `{{alias.x}}`, bridging UI and
  API transports unchanged.

See [`examples/demo/`](examples/demo/) for a complete two-app pack exercising
every feature.

**Docs:** [`src/uipilot/templates/skill.md`](src/uipilot/templates/skill.md) — the
agent guide, shipped and installed by `uipilot init` (core loop, execution
contract, safety) · [`docs/USE_CASES.md`](docs/USE_CASES.md) — business use cases
at a glance · [`docs/PACK_AUTHORING.md`](docs/PACK_AUTHORING.md) — pack field
reference and porting checklist.

---

## Commands

| Command | Purpose |
|---|---|
| `apps` | List apps, base URLs, auth entry flows |
| `actions` | List/filter actions (`--app --risk --grep --section --transport`) |
| `elements` | List/filter elements + resolved selectors |
| `show action <id>` / `show element <id>` | Full detail, selectors resolved inline |
| `uses <id>` | Reverse index — change blast radius before you edit |
| `flows` / `flow <name> [--params]` | List / show named flows (`--params`: aggregated param manifest only) |
| `path --from <a> --to <b>` | BFS a route through the flow graph |
| `script …` | **Emit an executable Playwright-MCP script** (see below) |
| `validate` | Lint the model statically (CI gate) |
| `verify …` | Emit a read-only probe to detect live UI drift |
| `emit --format pw-pom\|pw-test` | Generate Python POM classes / a pw-test spec |
| `capabilities [--check]` | List (and import-check) the pack's auth adapters |
| `init [dir] [--agent claude\|agents] [--force]` | Scaffold a pack + agent instructions in a project |
| `import-md <file> --out <dir>` | One-time: seed a pack from a retired Markdown map |

### `script`

```
uipilot script (--flow <name> | --from <a> --to <b> | --actions a,b,c)
               [--params file.json] [--set key=value ...]
               [--skip-auth] [--batch] [--refuse-destructive]
               [--format playwright-mcp|steps|json|pw-test|human]
```

* **`--format human`** emits a plain-English preview (numbered steps, params,
  risk, teardown) for a person to review before an agent runs a risky flow.

* **Param resolution:** `--set` > `--params` > model defaults. Defaults expand
  pack tokens (`{{prefix}}`, `{{seq}}`). Unresolved **required** params are
  emitted as `{{placeholder}}` and listed under `params_required`.
* **Secrets** (`type: secret`) never appear in the header echo — only in the one
  step that consumes them.
* **`--refuse-destructive`** refuses to emit if any action on the path carries a
  `risk` in the pack's `risk.gated` set. The header always surfaces `risk_max`.
* **`--batch`** collapses consecutive form fills into one `browser_fill_form`.

---

## `validate` vs `verify`

* **`validate`** (offline, CI-gating) — internal consistency only: dangling
  refs, broken edges, undeclared params, capture collisions, unreachable nodes,
  unbound API calls, coverage bypass. Answers *"is the map self-consistent?"*
* **`verify`** (live) — emits a read-only probe (navigate + snapshot +
  assert-each-element-resolves; no mutating clicks) the agent runs against the
  app. Answers *"does the map still match the running UI?"* `--drive` walks a
  full flow but **refuses `risk.gated` steps** unless `--allow-gated`.

Lint codes: `E_DANGLING_ELEMENT`, `E_BROKEN_EDGE`, `E_SELECTOR_AMBIGUOUS`,
`E_PARAM_UNDECLARED`, `E_SUBFLOW_CYCLE`, `E_CAPTURE_COLLISION`,
`E_API_CALL_UNBOUND`, `W_NO_STEPS`, `W_UNREACHABLE`, `W_NO_CAPTURE`,
`W_DUPLICATE_RECIPE`, `W_UI_COVERAGE_BYPASS`, `W_UNMET_REQUIRES`.

---

## Development

```bash
uv sync          # installs the project + the dev dependency group
uv run pytest -q
```

### Architecture

The package is split into four layers under `src/uipilot/`, with dependencies
pointing strictly **inward** (`presentation → application → {domain,
infrastructure} → domain`):

```
domain/          pure model + business rules (no I/O, no frameworks)
  model            entities: App, Element, Action, Flow, Step, Param, Capture, Selector, Pack
  templating       RuntimeContext + {{token}} resolution
  flows            subflow expansion (single source of truth)
  graph            BFS pathfinding + reachability
  validation       the static linter (E_/W_ codes)
  compiler         flow → CompiledScript
  verification     read-only drift-probe builder
  usage            reverse index
infrastructure/  I/O and external concerns
  pack_loader      YAML → domain model
  capabilities     dynamic import of pack auth adapters
  markdown_importer  one-shot MD → seed YAML
application/     use-case orchestration
  service          open_pack + compile/validate/verify/route/uses/… wiring
presentation/    the CLI and output renderers
  cli              Typer entrypoint (talks only to application)
  renderers        json / playwright-mcp / steps / pw-test / pw-pom
```

The domain layer imports nothing outside the standard library, so the business
rules are testable with no YAML, filesystem, or CLI in the loop.

## License

MIT.
