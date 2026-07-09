---
name: uipilot
description: >-
  Compile web-UI flows into Playwright-MCP-executable scripts from a structured
  pack (a `.uipilot/` directory), and drive them with the Playwright MCP tools.
  Use for anything touching a uipilot pack — both running flows AND setting one
  up. Running: automate/run/test a web-UI flow (sign-in, create X, submit Y),
  check whether a UI map still matches the live app (drift), find a click-path
  between screens, generate @playwright/test specs or Page Objects, or explore
  an app's action/element graph. Authoring/setup: create or edit the pack's
  `.uipilot/.env`, add credentials/base-URLs for a stand/tenant, wire login
  secrets to a sign-in flow, scaffold a new pack, or map a new app/flow/element.
  Triggers: "run/automate/test the … flow", "click through to …", "does the map
  still match", "generate a Playwright test/POM", "what breaks if I change this
  selector", "add credentials / create the .env for the pack", "set up the
  .uipilot pack", "configure the stand/tenant", "map a new flow/element",
  anything mentioning ".uipilot".
---

# uipilot — agent guide

uipilot is **emit-only**: it turns a per-app *pack* (YAML map of a UI) into
structured JSON. It executes nothing. **You** run the emitted steps via the
Playwright MCP tools (`browser_navigate`, `browser_snapshot`, `browser_click`, …).

Output is JSON on stdout (agent-consumable). Exit codes: `0` ok · `1` validate
found errors · `2` usage error / not found.

## Invocation

```
uipilot [--pack DIR] [--format json|table|md] <command> [opts]
```

- `--pack`: pack dir. Default = `$UIPILOT_PACK` → `.uipilot/` in cwd → bundled example.
- Keep `--format json` (default) for machine use; `table`/`md` are for humans.

## Command map

| Command | Purpose |
|---|---|
| `apps` | list apps, base URLs, auth entry flows |
| `flows` / `flow NAME [--params]` | list flows / show one flow (`--params`: just the aggregated param manifest — cheap, no compile) |
| `actions [--app --section --risk --grep --transport ui\|api]` | list/filter actions (graph nodes) |
| `elements [--app --action --section --grep]` | list elements + resolved selectors |
| `show action ID` / `show element ID` | full detail (selectors inline, step recipe) |
| `uses REF` | reverse index — what breaks if you edit an element/action/flow |
| `path --from A --to B [--max-depth 25]` | shortest click-path between UI actions |
| **`plan --flow NAME`** | **one-shot brief: app + guard + param manifest + compiled script in one call** (collapses apps→flow→--params→script) |
| **`script`** | **emit the executable script** (see below) |
| `validate [--app]` | static lint the map (CI health); exit 1 on errors |
| `verify [--flow\|--app\|--action] [--drive] [--allow-gated]` | read-only drift probe vs live app |
| `emit --format pw-pom\|pw-test [--app] [--flow]` | build artifacts: POM classes / @playwright/test spec |
| `capabilities [--check]` | list (and binding-check) the pack's auth adapters |
| `init [DIR] [--agent claude\|agents]` | scaffold a pack skeleton + this skill (usually run once by the human) |
| `update [DIR] [--agent claude\|agents]` | refresh this skill / AGENTS.md to the installed uipilot version; never touches the pack |
| `import-md FILE --out DIR` | one-time: seed a pack from a legacy markdown map |

## The core loop (running a flow)

**Two standing rules whenever a user asks you to run/pass a flow:**

- **Drive via a compiled script — don't hand-drive the UI element-by-element.**
  Always compile the flow (`uipilot script --flow …`) and execute *its* steps.
  Never free-form your way through with ad-hoc `browser_snapshot` →
  reason-about-this-element → click; that per-element guessing is exactly what the
  pack exists to replace. If no flow/pack covers the request yet, author the pack
  first (see **Authoring & maintaining a pack**), then compile — don't fall back to
  hand-driving.
- **Default to a visible browser you can watch; only go headless if asked.** A
  flow can run in a *visible* (headed) browser — the **default**, good for demos
  and risky/first runs — or *headless* in the background (faster, for known-good
  automation). Run headed unless the user explicitly asks to run it in the
  background. This is set by how the **Playwright MCP server** was launched — a
  server-launch setting, not a per-call tool arg:
  - **Watch (default)** → the MCP server must be running **headed** (visible
    window), ideally with a `slowMo` launch option so steps are followable. If it's
    currently headless, tell the human to relaunch the MCP server headed (+ slowMo)
    before you start — you can't toggle it mid-session.
  - **Background** → a **headless** MCP server. Use only when the user asks for it.

**Fast path — one call covers discovery.** `uipilot plan --flow NAME` returns the
app (id + base URL + auth entry flow), the flow `guard`, the full param manifest,
**and** the compiled `script` in a single JSON — collapsing steps 1–5 below. Reach
for `plan` first; drop to the individual commands only when you need to explore
(`flows`/`actions`/`path`) or drift-check (`verify`). `plan` takes the same
`--set`/`--params`/`--skip-auth`/`--batch`/`--refuse-destructive` as `script`.

1. **Pick the app**: `uipilot apps`. **If it returns >1 app**, don't guess "the app" — match the user's wording to an app `id`/`base_url`, else ask which. Login/auth flows are each app's `auth_entry_flow`.
2. **Find the flow**: `uipilot flows` → pick an id. `uipilot flow NAME` inspects path/params **and any `guard`** — a cheap `expect`/`wait_for` meaning "already done, skip if it passes" (e.g. auth flows guard on a signed-in marker). The guard also rides into `plan`/`script` output as the auth precondition's `skip_if` (see the contract), so for sign-in you snapshot once and skip if it matches — no separate lookup.
3. **(Optional) drift-check first**: `uipilot verify --flow NAME` → read-only probe; if an element/route fails to resolve, the map is stale — stop and report.
4. **Know the params up front**: `plan` includes the manifest; or `uipilot flow NAME --params` returns it alone (flow-level **and** every action's params, deduped) — `required`, `secret`, `enum`, `satisfied_by` — so you gather values once instead of compile→read→recompile.
5. **Compile**: `uipilot plan --flow NAME` (or `script --flow NAME`) — `--format playwright-mcp` is the `script` default. Add `script --format human` for a plain-English preview to show a human before running a risky flow.
6. **Supply params**: `--set key=value` (repeatable) or `--params file.json`. Everything in `params_required` MUST be provided (secrets are required there and never echoed) — but first check `params_satisfiable`: a param listed there is already available from the environment (e.g. `{"password": {"source": "env:TENANT_PASSWORD", "present": true}}`), so supply it with `--set password=$TENANT_PASSWORD` instead of hunting for the value or asking the human.
7. **Execute the JSON** (contract below) with Playwright MCP tools, then **report** (see below).

```
uipilot script --flow create_project_with_credential \
  --set project_name=acme --set password=$PW --format playwright-mcp
```

### Execution contract (the `script` JSON)

```
flow, app, requires_auth[], risk_max, crosses_app,
params{echo}, params_required[], param_capabilities{param: capability},
params_satisfiable{param: {source, present}}, preconditions[], steps[],
crosschecks[], teardown[], refused?, executor{tool_prefix}
```

`executor.tool_prefix` (playwright-mcp output only) is how each step's **bare**
`mcp.tool` maps onto your namespaced MCP registry: the tool you actually call is
`tool_prefix + name`, e.g. `browser_navigate` → `mcp__playwright__browser_navigate`.
Prepend it rather than calling the bare name (which won't resolve).

Run in order:

1. **`preconditions`** first (each has `run_by: "agent"`):
   - `kind: auth` → **first take a `browser_snapshot`; if this precondition's `skip_if` marker (e.g. `{"text": "Service Wallets"}`) is already present, you are signed in — skip auth entirely.** Otherwise reuse Playwright `storageState` for `storage_state_key` if present/fresh, else run the sign-in `flow` and re-save state.
   - `kind: api_action` → invoke `call` (`module:function`, a test factory/client) with `args`; keep its `captures`. These are setup, done via API not UI.
2. **`steps`** in order. Each carries `mcp: {tool, args}` — call that exact tool.
   - An `op: snapshot` step → call `browser_snapshot`; it returns element `ref`s.
   - Interacting steps have `args.ref: "@snapshot"` → substitute the ref for that step's `element` from the **latest** snapshot. Re-snapshot after `navigate`/`wait_for`.
   - `optional: true` → skip silently if the element isn't present.
   - `{{captured.X}}` in a value → fill from an earlier step/precondition's capture.
3. **`crosschecks`** → `api_action`s that assert backend state (e.g. verify the record the UI just created), using `{{captured.*}}`.
4. **`teardown`** last → `api_action`s that delete what the flow created (keyed by `{{captured.*}}`). Run them even if a step failed, so a partial run leaves no orphan data.

If `refused` is set, the path carries gated risk under `--refuse-destructive` — do **not** execute; report the reason.

## On failure, and reporting the run

- **A step fails** (element won't resolve, wait times out): do **not** thrash-retry or guess selectors. Run `uipilot verify --action <the step's action id>` — a targeted read-only probe. If it reports drift, the map is stale: **stop and report** which element/route drifted; do not keep driving. (`verify --flow NAME` re-probes the whole flow if you need wider scope.)
- **Always finish with a `run_report`** so the human who verifies your work doesn't have to reconstruct it from the transcript. Emit this exact shape:

```jsonc
{
  "flow": "create_project_with_credential",
  "status": "ok" | "failed" | "refused",
  "steps_run": 36, "steps_total": 36,
  "failed_step": null,          // or { "n": 20, "action": "act_cs_create_project", "reason": "..." }
  "captures": { "project_id": "…", "credential_id": "…" },
  "crosschecks": [ { "id": "api_assert_operation", "passed": true } ],
  "teardown": [ { "id": "api_delete_project", "done": true } ],
  "drift": null,                // or { "element": "cs_btn_...", "expected": {…}, "seen": "…" }
  "notes": "free text for the human"
}
```

Keep secret values out of the report (echo their param key, never the value).

## Safety

- **Secrets** (`type: secret`, e.g. password/MFA) are never printed; they appear only in the consuming step and only when you passed them. Missing ones are listed in `params_required`. Before asking a human, check two maps: **`params_satisfiable`** (e.g. `{"password": {"source": "env:TENANT_PASSWORD", "present": true}}`) — the value is already in the environment, so pass `--set password=$TENANT_PASSWORD`; and **`param_capabilities`** (e.g. `{"mfa_code": "totp"}`) — a capability can mint it, so resolve it yourself via the adapter (`uipilot capabilities` lists them). Only a genuinely un-mintable, un-env-backed secret (a human's password not on disk) should be requested.
- `risk_max` / `crosses_app` tell you the blast radius before running.
- **Gated risk** (e.g. `destructive`, `money-moving`): to only drift-check without side effects use `verify --flow NAME --drive` (walks the flow but refuses gated steps); add `--allow-gated` only when you truly intend the side effect. Add `--refuse-destructive` to `script` to hard-block emission of gated paths.

## Authoring & maintaining a pack

**You own the pack.** The human supplies only URLs, credentials, and rules — you
explore the app and write the YAML. This is the full schema; nothing else is
needed. Author or edit a pack when: there is no pack yet (or it's an empty
scaffold), `verify` reports drift, or a new flow/element must be mapped. After
any edit run `uipilot validate` until clean, then `uipilot script <flow>`.

A pack is a directory (`.uipilot/` by default) with `flowmap.config.yaml`,
`data/<app>.app.yaml` (one per app), `data/flows.yaml`, and `capabilities.py`.

### `flowmap.config.yaml`

```yaml
pack: myapp
apps: [console, portal]        # each id needs a data/<id>.app.yaml
tokens:                        # expansions usable in param defaults
  prefix: { from: env, name: TEST_ENTITY_PREFIX, default: "test" }
  seq:    { from: counter }    # per-run monotonic counter, stable within a run
risk:                          # YOUR taxonomy, low → most dangerous (data, not engine code)
  levels: [low, admin-control, credential, destructive, money-moving]
  gated:  [destructive, money-moving]   # what --refuse-destructive blocks
capabilities:                  # named adapters the engine invokes by key (see capabilities.py)
  totp:          { impl: "capabilities:totp_from_secret" }
  storage_state: { impl: "capabilities:playwright_storage_state" }
```

**Env-bound values via `.uipilot/.env`.** Any `{ from: env, name: X }` token and
every app `base_url { env: X }` resolves `X` from the process environment — and,
as a default, from an optional **`.uipilot/.env`** file (`KEY=value` lines). Put
per-project config there — base URLs, and credentials for login flows (e.g.
`APP_EMAIL` / `APP_PASSWORD` wired to tokens a sign-in action's `fill` steps
reference as `{{email}}`/`{{password}}`). A real shell variable of the same name
overrides the file. `.env` is git-ignored by default — never commit real
secrets; reference them from the pack, don't inline them.

### `data/<app>.app.yaml`

```yaml
app:
  id: console
  base_url: { env: CONSOLE_UI_URL, default: "http://127.0.0.1:4001" }
  id_prefix: cs                  # namespace prefix for THIS app's element/action ids
  auth:
    entry_flow: console_sign_in  # prepended as an auth precondition unless --skip-auth
    storage_state_key: console   # Playwright storageState reuse key
elements:
  cs_btn_create:                 # id is globally unique; prefix it with id_prefix
    type: button                 # free-form (button/input/dialog/tab/link/table/row/text/toast/…)
    section: "Projects list"     # optional grouping label
    selector: { strategy: role, role: button, name: "Create" }
    purpose: "Open the create dialog"
actions:
  act_cs_create:
    purpose: "Create a project."
    route: "/projects"           # base_url+route → navigate step; may template {{params}}
    risk: low                    # must be one of config.risk.levels
    elements: [cs_btn_create, cs_input_name, cs_toast_created]
    prev: [act_cs_open_projects] # graph edges (drive `path`/`next`/`prev`)
    next: []
    params: [ { key: name, type: string, required: true, default: "{{prefix}}-{{seq}}" } ]
    steps:
      - { op: click,    element: cs_btn_create }
      - { op: fill,     element: cs_input_name, value: "{{name}}" }
      - { op: click,    element: cs_btn_submit }
      - { op: wait_for, element: cs_toast_created }
    captures: [ { key: id, from: url, pattern: "/projects/(?<id>[0-9a-f-]{36})" } ]
```

### Field reference

| Entity | Fields |
|---|---|
| `App` | `id`, `package?`, `base_url{env, default}`, `id_prefix`, `auth{entry_flow, storage_state_key}?` |
| `Element` | `id`, `type`, `section?`, `selector{…}`, `purpose?` |
| `Action` (ui, default) | `purpose`, `route`, `risk`, `elements[]`, `prev[]`, `next[]`, `params[]`, `steps[]`, `captures[]`, `requires[]?`, `provides[]?` |
| `Action` (api) | `transport: api`, `role` (`setup`\|`crosscheck`), `purpose`, `risk`, `call` (`"module:function"`), `params[]`, `captures[]`, `requires[]?`, `provides[]?` — **no** `route`/`elements`/`steps`/`prev`/`next` |
| `Param` | `key`, `type` (`string`\|`enum`\|`secret`\|`address`\|`amount`\|`int`), `required?`, `default?`, `enum[]?`, `satisfied_by?` (capability key that mints the value, e.g. a `secret` `mfa_code` with `satisfied_by: totp`) |
| `Step` | `op`, `element?`, `value?`, `wait_for?` (`{text}`\|`{textGone}`\|`{time}`), `scope?`, `optional?` |
| `Capture` | `key`, `from` (`url`\|`element`\|`clipboard`\|`response`), `pattern?` (regex w/ named group), `path?` (JSONPath for `response`), `element?` |

**Templated routes — reach detail pages by URL.** A `route` may contain `{{param}}`/`{{token}}`
refs, e.g. `route: "/clients/{{client_id}}/wallets/{{wallet_id}}"` with matching `params`. At
`script` time a supplied value (`--set client_id=…`) substitutes into the navigate URL; an
unsupplied required param is listed in `params_required` and left as a `{{placeholder}}` for the
agent. Navigations dedup on the **resolved** URL (same concrete URL collapses; distinct ids don't).
Prefer a templated route over clicking through table rows when a page is URL-addressable — it's
deterministic and needs no per-row selector. `validate` flags a route templating an undeclared param.

### Selectors — prefer structural CSS (or XPath); never anchor on text

Selectors are stored **structurally**, never as a raw locator string, so they
stay lintable and re-emittable. Keys: `strategy`, `role`, `name`, `text`,
`label`, `css`, `testid`, `scope`, `exact`. Supported strategies: `css` ·
`testid` · `label` · `role` · `text`. `name` applies only to `role`/`label`/`text`.

**Default authoring policy — chosen for robustness against minor UI changes:**

- **Default to `css`.** Anchor on stable structure — an `id`, a `data-*` /
  `data-testid` attribute, or a stable class/DOM path:
  `{ strategy: css, css: "[data-testid='submit']" }`. Reach for this first.
- **Use XPath only when CSS can't express it** (axis/position, structural
  relationships CSS lacks). There is **no dedicated `xpath` strategy** — ride the
  `css` strategy with an `xpath=`/`//…` string; Playwright's `locator()`
  auto-detects it: `{ strategy: css, css: "xpath=//tr[2]//button" }`.
- **Never anchor on element text.** Do **not** use `strategy: text` — and avoid
  the content-derived `role`+`name`/`label` forms, which share the same fragility
  — **unless the user explicitly instructs you to.** Visible copy shifts with
  translations, wording tweaks, and A/B tests, so text-based selectors break
  first.

A UI map or a live snapshot often hands you Playwright locator expressions or
role/text descriptions — **translate them to a `css` anchor** rather than storing
them as-is. Find the structural attribute behind the element:

| You're handed | Author as (preferred) |
|---|---|
| a `data-testid` / `data-*` attribute | `{ strategy: css, css: "[data-testid='submit']" }` |
| a stable `id` | `{ strategy: css, css: "#submit" }` |
| `getByTestId('submit')` | `{ strategy: css, css: "[data-testid='submit']" }` (or `{ strategy: testid, testid: "submit" }`) |
| structure CSS can't reach | `{ strategy: css, css: "xpath=//tr[2]//button" }` |
| dialog's *Create* vs the page's *Create* | scope in css: `{ strategy: css, css: "[role=dialog] [data-testid='create']" }` |

**Only when the user explicitly opts into text/role selectors** do the
content-based forms apply: `getByRole('button', { name: 'Save' })` →
`{ strategy: role, role: button, name: "Save" }`; `getByLabel('Password')` →
`{ strategy: label, label: "Password" }`; `getByText('…')` →
`{ strategy: text, text: "…" }`. There, `name` is a **normalized,
case-insensitive substring** match (`exact: true` forces a full match); pick the
one literal the live app actually renders (snapshot if unsure).

### Step ops → Playwright-MCP tool

`navigate`→`browser_navigate` (base_url+route) · `snapshot`→`browser_snapshot`
(auto-inserted where the DOM changes) · `click`→`browser_click` ·
`fill`/`type`→`browser_type` (or batched `browser_fill_form`) ·
`select`→`browser_select_option` · `press`→`browser_press_key` ·
`wait_for`→`browser_wait_for` (`{text}`/`{textGone}`/`{time}`, or derived from the
awaited `element`) · `expect`→snapshot+assert · `capture`→url read /
`browser_evaluate` · `upload`→`browser_file_upload`. Interacting ops
(`click`/`fill`/`type`/`select`/`press`/`upload`) act on a fresh snapshot ref, so
end a screen-changing step with a `wait_for` before the next interaction.

### `data/flows.yaml`

A `path` entry is one of: a bare action id · `{ use: <flow-id> }` (inline a
subflow) · `{ action: <id>, as?: <alias>, params?: {…} }` (aliased invocation;
`as:` namespaces its captures so an action can repeat).

```yaml
actions:                          # (optional) API actions, shared across flows
  api_create: { transport: api, role: setup, app: console, call: "factories.x:create",
                captures: [ { key: id, from: response, path: "$.id" } ] }
  api_delete: { transport: api, role: setup, app: console, call: "factories.x:delete",
                params: [ { key: id, type: string, required: true } ] }
flows:
  console_sign_in:                # L2 subflow, authored once, embedded anywhere
    app: console
    guard: { expect: { text: "Current session" } }   # L4: skip the flow if already true
    path: [act_cs_sign_in, act_cs_mfa]
  create_project:
    app: console
    path:
      - use: console_sign_in
      - act_cs_open_projects
      - { action: act_cs_create, params: { name: "{{prefix}}-a" } }
    teardown:                     # API deletes run after the flow, even on failure
      - { action: api_delete, params: { id: "{{captured.id}}" } }
```

Captures bridge transports: an API `from: response` capture flows into a later
UI step as `{{alias.key}}`, exactly like a UI `from: url` capture. A flow's
`guard` is the "already done, skip if it passes" marker `flow NAME` surfaces.

### `capabilities.py`

The one place the pack hands executable Python to the engine (a TOTP generator,
a storageState reader). Have these **call existing test-framework helpers**
rather than reimplement auth. The engine never runs them during emit — it only
import-checks them (`uipilot capabilities --check`).

### Seeding from a legacy markdown map

`uipilot import-md MAP.md --out <pack>` harvests element/action **ids** grouped
by prefix but leaves every `selector`, `purpose`, and `steps` as `TODO` (it
exits non-zero to flag the pack as unfinished). Treat it as a scaffold, not a
finished pack: fill each `selector` from the map's locator expressions per the
table above, write the `steps` recipes and `prev`/`next` edges, then `validate`.

## When to use which

- "Run/automate/test flow X" → `plan --flow X` (one-shot app+guard+params+script) → execute (core loop); or `script --flow X` if you already have the app/params.
- "Click from screen A to B" → `path --from A --to B`, then `script --actions <path>` or `--from/--to`.
- "Does the map still match the app?" → `verify` (probe) or `verify --drive` (walk).
- "Is the map internally consistent?" → `validate` (offline; run in CI).
- "What breaks if I change this selector/action?" → `uses REF`.
- "Give me a Playwright test / Page Object" → `emit --format pw-test --flow X` / `emit --format pw-pom`.
- Params come from the caller; if unknown, read `params_required` from a dry `script` run and ask for exactly those.

## Notes

- No engine domain vocabulary: apps/risk levels/tokens are all defined by the pack's `flowmap.config.yaml`. Read `apps` and `flows` before assuming ids.
- `--batch` collapses adjacent field fills into one `browser_fill_form` (fewer round-trips).
- `--skip-auth` drops the auth precondition (use only when already signed in).
- **You own the pack.** The human supplies only URLs, credentials, and rules; you explore the app (drive it with Playwright MCP, `browser_snapshot` each screen) and author the pack yourself — see **Authoring & maintaining a pack** above for the full schema. When `verify` reports drift, fix the offending element's selector in the YAML from the fresh snapshot and re-run `validate`; don't wait for a human to patch it.
