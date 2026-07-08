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
- **You own the pack.** The human supplies only URLs, credentials, and rules; you explore the app (drive it with Playwright MCP, `browser_snapshot` each screen) and author the pack yourself — see `docs/PACK_AUTHORING.md`. When `verify` reports drift, fix the offending element's selector in the YAML from the fresh snapshot and re-run `validate`; don't wait for a human to patch it.
