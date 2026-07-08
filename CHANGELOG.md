# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-07-08

### Added

- **Selector authoring policy in the agent guide.** `skill.md` now defaults to
  structural **CSS** selectors (`id`/`data-*`/`data-testid`/DOM path), falling
  back to **XPath** only when CSS can't express the target — expressed via the
  `css` strategy with an `xpath=`/`//…` string, which Playwright's `locator()`
  auto-detects (there is no separate `xpath` strategy). Text-based selectors
  (`strategy: text`, and content-derived `role`/`label` anchors) are now used
  **only when the user explicitly asks**, since visible copy is the first thing to
  break on minor UI changes. README's element description updated to match.
- **Run-a-flow policy in the agent guide.** `skill.md`'s core loop now opens with
  two standing rules: always drive a flow via a compiled `uipilot script` (never
  hand-drive the UI element-by-element), and default to running the flow in a
  **visible/headed** Playwright MCP browser (ideally with `slowMo`) so it's
  watchable — going **headless** only when the user asks for a background run.
  Browser visibility is a server-launch setting, not a per-call arg.
- **Route templating.** An action's `route` now resolves `{{param}}`/`{{token}}`
  refs (e.g. `route: "/projects/{{project_id}}"`), so URL-addressable detail
  pages can be reached by navigation instead of only by clicking through table
  rows. Supplied params (`--set project_id=…`) substitute into the navigate URL;
  unsupplied required params are reported in `params_required` and left as a
  `{{placeholder}}`. Navigations dedup on the **resolved** URL. `verify` resolves
  route tokens too, and `validate` now flags a route that templates an undeclared
  param (`E_PARAM_UNDECLARED` — message reads `route uses {{x}}…`).

### Changed

- **Test suite reorganised into `unit`/`integration`/`e2e`** with matching
  pytest markers, plus branch coverage, `pytest-xdist` for parallel runs, and a
  stricter static-analysis config (added ruff `S`/`SIM`/`RET`/`PTH`/`RUF` rule
  sets, `ty` `unresolved-import = error`, and vulture `min_confidence = 80`).

## [0.3.0] - 2026-07-08

### Changed

- **`uipilot init` now writes only the Claude Code skill by default** (`.claude/skills/uipilot/SKILL.md`).
  `AGENTS.md` is no longer created unless you opt in with `--agent agents`
  (e.g. `uipilot init --agent claude --agent agents`).
- **The shipped agent guide (`skill.md`) is now the single source of truth**,
  carrying the full pack authoring schema (config, app/element/action/flow field
  reference, selector conversion, step ops) in a new *Authoring & maintaining a
  pack* section.
- Bumped runtime dependencies (`typer>=0.26.8`, `rich>=15.0.0`, `pyyaml>=6.0.3`)
  and dev tooling (`pytest-cov`, `ruff`, `ty`, `vulture`).

### Removed

- **`docs/PACK_AUTHORING.md`** — its content is now folded into the shipped
  skill so authors and agents read one canonical guide.

## [0.2.0] - 2026-07-08

### Changed

- **`uipilot init` now scaffolds the pack under `.uipilot/`** (e.g.
  `.uipilot/flowmap.config.yaml`, `.uipilot/data/`, `.uipilot/capabilities.py`)
  instead of the project root. Agent instruction files (`.claude/skills/uipilot/`,
  `AGENTS.md`) are still written at the project root.
- **Pack auto-discovery** now resolves a `.uipilot/` pack in the cwd:
  `$UIPILOT_PACK` → `<cwd>/.uipilot/` → the bundled example. The previous
  root-of-cwd `flowmap.config.yaml` fallback has been removed; pass `--pack` or
  set `$UIPILOT_PACK` to use a pack elsewhere.

### Fixed

- Applied `ruff format` across the codebase and added a `vulture_whitelist.py`
  per-file lint ignore so the full quality-check suite (ruff, ty, vulture,
  pytest coverage) passes cleanly.

## [0.1.0] - 2026-07-08

Initial release.

### Added

- **Engine** that models a web UI as a graph (app, element, action, flow, step,
  param, capture, capability) and compiles flows into Playwright-MCP-executable
  scripts, with selectors pre-resolved and page snapshots inserted only where
  the DOM changes. The engine ships no domain vocabulary; everything
  project-specific lives in a pack.
- **CLI** (`uipilot`) with commands to explore and compile packs: `apps`,
  `actions`, `elements`, `uses`, `flows`, `flow`, `path`, `script`, `show`, and
  `capabilities`.
- **`uipilot init`** to scaffold a pack plus agent instructions so an agent can
  start using uipilot in a project.
- **`uipilot validate`** for static linting of the model (dangling refs, broken
  edges, unreachable nodes).
- **`uipilot verify`** to emit a read-only probe script that detects live drift
  against the running app.
- **`uipilot emit`** to generate build artifacts: Python POM classes (`pw-pom`)
  or a Playwright test spec (`pw-test`).
- **`uipilot import-md`** to parse a retired `UI_FLOW_MAP.md` into seed pack YAML.
- **Human preview**, **param manifest**, **capability-satisfiable secrets**, and
  **teardown** support.
- **Agent guide** documentation and static-analysis tooling (ruff, ty, vulture).

[Unreleased]: https://github.com/l0kifs/uipilot/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/l0kifs/uipilot/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/l0kifs/uipilot/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/l0kifs/uipilot/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/l0kifs/uipilot/releases/tag/v0.1.0
