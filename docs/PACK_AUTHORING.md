# Pack authoring & porting

A **pack** is all the project truth `uipilot` needs, as data. The engine has no
knowledge of your domain — it loads a pack and works entirely from it. This is
the field reference; see [`examples/demo/`](../examples/demo/) for a worked
two-app pack.

## `flowmap.config.yaml`

```yaml
pack: demo
apps: [console, portal]        # each needs a data/<id>.app.yaml

tokens:                        # expansions usable in defaults: {{prefix}}, {{seq}}
  prefix: { from: env, name: TEST_ENTITY_PREFIX, default: "demo" }
  seq:    { from: counter }    # per-run monotonic counter (stable within a run)

risk:                          # the risk taxonomy is DATA, not engine code
  levels: [low, admin-control, credential, destructive, money-moving]
  gated:  [destructive, money-moving]   # what --refuse-destructive blocks

capabilities:                  # named adapters the engine invokes by key
  totp:          { impl: "capabilities:totp_from_secret" }
  storage_state: { impl: "capabilities:playwright_storage_state" }
```

A minimal single-page app needs only `apps: [main]`, one token, and
`risk: { levels: [low, destructive], gated: [destructive] }`.

## `data/<app>.app.yaml`

```yaml
app:
  id: console
  base_url: { env: CONSOLE_UI_URL, default: "http://127.0.0.1:4001" }
  id_prefix: cs                  # namespace for this app's element/action ids
  auth:
    entry_flow: console_sign_in  # prepended as a precondition unless --skip-auth
    storage_state_key: console   # Playwright storageState reuse key

elements:
  cs_btn_create:
    type: button
    section: "Projects list"
    selector: { strategy: role, role: button, name: "Create" }
    purpose: "Open the create dialog"

actions:
  act_cs_create:
    purpose: "..."
    route: "/projects"
    risk: low
    elements: [cs_btn_create, ...]
    prev: [act_cs_open_projects]
    next: [act_cs_open_detail]
    params:   [ { key: name, type: string, required: true, default: "{{prefix}}-{{seq}}" } ]
    steps:
      - { op: click,    element: cs_btn_create }
      - { op: fill,     element: cs_input_name, value: "{{name}}" }
      - { op: wait_for, element: cs_toast_created }
    captures: [ { key: id, from: url, pattern: "/projects/(?<id>[0-9a-f-]{36})" } ]
```

### Field reference

| Entity | Fields |
|---|---|
| `App` | `id`, `package?`, `base_url{env, default}`, `id_prefix`, `auth{entry_flow, storage_state_key}` |
| `Element` | `id`, `type`, `section?`, `selector{strategy, role, name, text, label, css, testid, scope, exact}`, `purpose?` |
| `Action` (ui) | `transport: ui` (default), `purpose`, `route`, `risk`, `elements[]`, `prev[]`, `next[]`, `params[]`, `steps[]`, `captures[]`, `requires[]?`, `provides[]?` |
| `Action` (api) | `transport: api`, `role` (`setup`\|`crosscheck`), `purpose`, `risk`, `call`, `params[]`, `captures[]`, `requires[]?`, `provides[]?` — **no** `route`/`elements`/`steps`/`prev`/`next` |
| `Param` | `key`, `type` (`string`\|`enum`\|`secret`\|`address`\|`amount`\|`int`), `required`, `default`, `enum[]`, `satisfied_by?` (capability key that can mint the value — e.g. a `secret` `mfa_code` with `satisfied_by: totp`, so the agent resolves it instead of asking a human) |
| `Step` | `op`, `element?`, `value?`, `wait_for?`, `scope?`, `optional?` |
| `Capture` | `key`, `from` (`url`\|`element`\|`clipboard`\|`response`), `pattern?`, `path?`, `element?` |

### Step ops → Playwright-MCP

| `op` | MCP tool |
|---|---|
| `navigate` | `browser_navigate` (url = base_url + route) |
| `snapshot` | `browser_snapshot` (auto-inserted where the DOM changes) |
| `click` | `browser_click` |
| `fill` / `type` | `browser_type` (or batched `browser_fill_form`) |
| `select` | `browser_select_option` |
| `press` | `browser_press_key` |
| `wait_for` | `browser_wait_for` (`{text}`/`{textGone}`/`{time}`, or derived from the awaited element) |
| `expect` | `browser_snapshot` + assertion |
| `capture` | url read / `browser_evaluate` |
| `upload` | `browser_file_upload` |

## `data/flows.yaml`

A `path` entry is one of: a bare action id, `{ use: <flow-id> }` (inline a
subflow), or `{ action: <id>, as?: <alias>, params?: {…} }` (aliased invocation).

```yaml
actions:                          # API actions can live here, shared across flows
  api_create: { transport: api, role: setup, app: console, call: "factories.x:create", ... }
  api_delete: { transport: api, role: setup, app: console, call: "factories.x:delete",
                params: [ { key: id, type: string, required: true } ] }

flows:
  sign_in:                        # L2 subflow, authored once
    app: console
    guard: { expect: { text: "Current session" } }   # L4: skip if already true
    path: [act_cs_sign_in, act_cs_mfa]

  onboard_two:
    app: console
    path:
      - use: sign_in
      - { action: act_cs_create, as: primary,   params: { name: "{{prefix}}-a" } }  # L3
      - { action: act_cs_create, as: secondary, params: { name: "{{prefix}}-b" } }
    teardown:                     # API deletes run after the flow (even on failure)
      - { action: api_delete, params: { id: "{{captured.id}}" } }
```

A flow's optional `teardown:` is a list of API actions the agent runs after the
flow (and after any crosschecks) to delete what it created — keyed by the flow's
`{{captured.*}}` values. It keeps repeated/CI runs from leaving orphan test data.

Captures bridge transports: an API action's `from: response` capture flows into
a later UI step as `{{alias.key}}` exactly like a UI `from: url` capture.

## `capabilities.py`

The one place the pack hands executable Python to the engine (a TOTP generator,
a storageState reader). Real packs **call existing test-framework helpers**
rather than reimplement auth. The engine never runs them during emit — it only
import-checks them (`uipilot capabilities --check`).

## Porting checklist (new web app)

1. `uv pip install uipilot` (engine unchanged).
2. Write `flowmap.config.yaml`: `apps`, `tokens`, a `risk` taxonomy + `gated`
   subset, and any `capabilities`.
3. Author `data/<app>.app.yaml` per app: `app` header + `elements` (structured
   selectors) + `actions` (recipes + prev/next + params + captures).
4. Implement auth as ordinary flows in `flows.yaml`; back any non-UI step (TOTP,
   OTP) with a named capability adapter.
5. `uipilot validate` until clean, then `uipilot script` your first flow.
