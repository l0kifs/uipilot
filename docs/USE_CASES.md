# uipilot — business use cases

Emit-only engine: turns a YAML **pack** (map of a web app) into pre-resolved
Playwright-MCP scripts. The **agent** runs the browser; a **human** verifies.
Engine executes nothing.

Actors: **A** = AI agent (runtime) · **D** = pack author/dev · **H** = human verifier.

| # | Use case | Actor | Command | Value |
|---|---|---|---|---|
| 1 | Run/automate a UI flow (sign-in, create X, submit Y) | A | `script --flow N` | Selectors pre-resolved → lookup, not live reasoning |
| 2 | Click-path between two screens | A | `path --from A --to B` | BFS a route through the action graph |
| 3 | Drift-check: map still matches live app? | A | `verify --flow N` | Read-only probe; catch stale selectors before running |
| 4 | Static consistency lint (CI gate) | D | `validate` | Dangling refs, broken edges, unreachable, unbound calls |
| 5 | Change blast-radius before editing | D | `uses REF` | What breaks if I touch this element/action |
| 6 | Generate test artifacts | D | `emit --format pw-test\|pw-pom` | `@playwright/test` spec / Python POM classes |
| 7 | Explore the app graph | A/D | `apps` `actions` `elements` `flows` `show` | Discover ids, selectors, routes, params |
| 8 | Know required inputs up front | A | `flow N --params` | Aggregated param manifest, one lookup |
| 9 | Human preview before a risky run | H | `script --flow N --format human` | Plain-English steps + risk + teardown |
| 10 | API provisioning + backend cross-check | A | api actions in flow | Fast setup + assert UI-created record via REST |
| 11 | Bootstrap in a project | D | `init` | Scaffold pack skeleton + Claude skill (`--agent agents` for AGENTS.md) |
| 12 | Author / port a new app | A/D | fill pack + `validate` | New app = new pack, zero engine change |
| 13 | Seed a pack from a legacy MD map | D | `import-md FILE --out DIR` | One-time bootstrap |
| 14 | Auth/secret adapters (MFA, session) | A | `capabilities` | Mint secrets, reuse `storageState` |

## Core runtime loop (UC 1)
1. `apps` → pick app · `flows` → pick flow (check `guard`).
2. `flow N --params` → gather inputs (`required`, `secret`, `satisfied_by`).
3. *(opt)* `verify --flow N` → stop if drift.
4. `script --flow N --set k=v` → compile.
5. Execute JSON with Playwright MCP: `preconditions` → `steps` → `crosschecks` → `teardown`.
6. Emit a `run_report` for H.

## Safety model
- **Emit-only**: safe to point at money-moving flows.
- **Secrets** never echoed; `param_capabilities` says which the agent mints vs. asks H.
- **Risk taxonomy** is pack data; `risk_max`/`crosses_app` shown up front.
- **Gated risk** (destructive/money-moving): `--refuse-destructive` blocks emit;
  `verify --drive` walks without side effects.
- **Teardown** deletes created test data even on partial runs.

## Key concepts
- **Pack** — all project truth as data (`flowmap.config.yaml` + `data/*.yaml`).
- **Element** — structured selector (`role(name)` > `label` > `text` > `css`).
- **Action** — graph node: `route` + `steps` + `prev`/`next` + `params` + `captures`
  (UI), or `call:` factory (API, `transport: api`).
- **Flow** — ordered action path; reuse layered L1–L4 (shared → subflow → aliased → guard).
- **Capture** — value one action produces, consumed later as `{{captured.x}}`; bridges UI↔API.

See the shipped skill `src/uipilot/templates/skill.md` (installed by
`uipilot init`) for both running flows and the full pack authoring schema —
section **Authoring & maintaining a pack**.
