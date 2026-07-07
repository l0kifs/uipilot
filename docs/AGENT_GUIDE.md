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

- `--pack`: pack dir. Default = `$UIPILOT_PACK` → cwd pack → bundled example.
- Keep `--format json` (default) for machine use; `table`/`md` are for humans.

## Command map

| Command | Purpose |
|---|---|
| `apps` | list apps, base URLs, auth entry flows |
| `flows` / `flow NAME` | list flows / show one flow's path + params |
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
| `import-md FILE --out DIR` | one-time: seed a pack from a legacy markdown map |

## The core loop (running a flow)

1. **Pick the app**: `uipilot apps`. **If it returns >1 app**, don't guess "the app" — match the user's wording to an app `id`/`base_url`, else ask which. Login/auth flows are each app's `auth_entry_flow`.
2. **Find the flow**: `uipilot flows` → pick an id. `uipilot flow NAME` inspects path/params **and any `guard`** — a cheap `expect`/`wait_for` meaning "already done, skip if it passes" (e.g. auth flows guard on a signed-in marker). Guards appear here, **not** in `script` output, so for sign-in: check the guard / reuse an existing session before running the flow.
3. **(Optional) drift-check first**: `uipilot verify --flow NAME` → read-only probe; if an element/route fails to resolve, the map is stale — stop and report.
4. **Compile**: `uipilot script --flow NAME --format playwright-mcp` (default). A dry run (no params) is also how you discover what to ask for — read its `params_required`.
5. **Supply params**: `--set key=value` (repeatable) or `--params file.json`. Everything in `params_required` MUST be provided (secrets are required there and never echoed).
6. **Execute the JSON** (contract below) with Playwright MCP tools.

```
uipilot script --flow create_project_with_credential \
  --set project_name=acme --set password=$PW --format playwright-mcp
```

### Execution contract (the `script` JSON)

```
flow, app, requires_auth[], risk_max, crosses_app,
params{echo}, params_required[],
preconditions[], steps[], crosschecks[], refused?
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
3. **`crosschecks`** last → `api_action`s that assert backend state (e.g. verify the record the UI just created), using `{{captured.*}}`.

If `refused` is set, the path carries gated risk under `--refuse-destructive` — do **not** execute; report the reason.

## Safety

- **Secrets** (`type: secret`, e.g. password/MFA) are never printed; they appear only in the consuming step and only when you passed them. Missing ones are listed in `params_required`. **Before asking the user for a secret, run `uipilot capabilities`** — an adapter (e.g. `totp` → MFA codes, `storage_state` → session reuse) may generate it, so a required `mfa_code` need not come from the user.
- `risk_max` / `crosses_app` tell you the blast radius before running.
- **Gated risk** (e.g. `destructive`, `money-moving`): to only drift-check without side effects use `verify --flow NAME --drive` (walks the flow but refuses gated steps); add `--allow-gated` only when you truly intend the side effect. Add `--refuse-destructive` to `script` to hard-block emission of gated paths.

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
- Authoring/editing packs → see `docs/PACK_AUTHORING.md` (out of scope for running flows).
