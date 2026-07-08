---
name: uipilot
description: >-
  Compile web-UI flows into Playwright-MCP-executable scripts from a structured
  pack, and drive them with the Playwright MCP tools. Use when asked to
  automate/run/test a web-UI flow (sign-in, create X, submit Y), check whether a
  UI map still matches the live app (drift), find a click-path between screens,
  generate @playwright/test specs or Page Objects, or explore an app's
  action/element graph. Triggers: "run/automate/test the … flow", "click through
  to …", "does the map still match", "generate a Playwright test/POM", "what
  breaks if I change this selector".
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
| **`script`** | **emit the executable script** (see below) |
| `validate [--app]` | static lint the map (CI health); exit 1 on errors |
| `verify [--flow\|--app\|--action] [--drive] [--allow-gated]` | read-only drift probe vs live app |
| `emit --format pw-pom\|pw-test [--app] [--flow]` | build artifacts: POM classes / @playwright/test spec |
| `capabilities [--check]` | list (and binding-check) the pack's auth adapters |
| `init [DIR] [--agent claude\|agents]` | scaffold a pack skeleton + this skill (usually run once by the human) |
| `import-md FILE --out DIR` | one-time: seed a pack from a legacy markdown map |

## The core loop (running a flow)

1. **Pick the app**: `uipilot apps`. **If it returns >1 app**, don't guess "the app" — match the user's wording to an app `id`/`base_url`, else ask which. Login/auth flows are each app's `auth_entry_flow`.
2. **Find the flow**: `uipilot flows` → pick an id. `uipilot flow NAME` inspects path/params **and any `guard`** — a cheap `expect`/`wait_for` meaning "already done, skip if it passes" (e.g. auth flows guard on a signed-in marker). Guards appear here, **not** in `script` output, so for sign-in: check the guard / reuse an existing session before running the flow.
3. **(Optional) drift-check first**: `uipilot verify --flow NAME` → read-only probe; if an element/route fails to resolve, the map is stale — stop and report.
4. **Know the params up front**: `uipilot flow NAME --params` returns the full manifest (flow-level **and** every action's params, deduped) — `required`, `secret`, `enum`, `satisfied_by` — in one cheap lookup, so you gather values once instead of compile→read→recompile.
5. **Compile**: `uipilot script --flow NAME --format playwright-mcp` (default). Add `--format human` for a plain-English preview to show a human before running a risky flow.
6. **Supply params**: `--set key=value` (repeatable) or `--params file.json`. Everything in `params_required` MUST be provided (secrets are required there and never echoed).
7. **Execute the JSON** (contract below) with Playwright MCP tools, then **report** (see below).

```
uipilot script --flow create_project_with_credential \
  --set project_name=acme --set password=$PW --format playwright-mcp
```

### Execution contract (the `script` JSON)

```
flow, app, requires_auth[], risk_max, crosses_app,
params{echo}, params_required[], param_capabilities{param: capability},
preconditions[], steps[], crosschecks[], teardown[], refused?
```

Run in order:

1. **`preconditions`** first (each has `run_by: "agent"`):
   - `kind: auth` → reuse Playwright `storageState` for `storage_state_key` if present/fresh; else run the sign-in `flow` and re-save state.
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

- **Secrets** (`type: secret`, e.g. password/MFA) are never printed; they appear only in the consuming step and only when you passed them. Missing ones are listed in `params_required`. The `script` output's **`param_capabilities`** map (e.g. `{"mfa_code": "totp"}`) names, per param, a capability that can mint it — resolve those yourself via the adapter (`uipilot capabilities` lists them) instead of asking the human. Only genuinely un-mintable secrets (a human's password) should be requested.
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
    route: "/projects"           # appended to base_url for the navigate step
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

### Selectors — convert Playwright locator expressions to structured form

Selectors are stored **structurally**, never as a raw `getByRole(...)` string, so
they stay lintable and re-emittable. Strategies: `role` · `label` · `text` ·
`testid` · `css` (author priority in that order). Keys: `strategy`, `role`,
`name`, `text`, `label`, `css`, `testid`, `scope`, `exact`. `name` applies only
to `role`/`label`/`text`.

A UI map (or a live snapshot) usually gives you Playwright locator expressions —
convert each one:

| Locator expression | Structured selector |
|---|---|
| `getByRole('button', { name: 'Save' })` | `{ strategy: role, role: button, name: "Save" }` |
| `getByRole('textbox', { name: 'Email' })` | `{ strategy: role, role: textbox, name: "Email" }` |
| `getByLabel('Password')` | `{ strategy: label, label: "Password" }` |
| `getByText('No tenants yet')` | `{ strategy: text, text: "No tenants yet" }` |
| `getByTestId('submit')` | `{ strategy: testid, testid: "submit" }` |
| CSS / `data-*` | `{ strategy: css, css: ".panel [data-role=x]" }` |
| dialog's *Create* vs the page's *Create* | add `scope: dialog` → emits `getByRole('dialog').getByRole('button', { name: 'Create' })` |

`name` is a **normalized, case-insensitive substring** match by default. So a
map entry written as a regex — `name: /code/i`, `name: /Copy ID/` — becomes a
plain literal: `{ strategy: role, role: textbox, name: "code" }`. Add
`exact: true` only to force a full exact-name match. For an alternation regex
like `/verify|submit/i`, pick the one literal the live app actually renders
(snapshot it if unsure); for a name that varies per row/record, prefer a
`testid` or a stable `text`/`css` anchor over a brittle `name`.

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

- "Run/automate/test flow X" → `script --flow X` → execute (core loop).
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
