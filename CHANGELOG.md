# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/l0kifs/uipilot/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/l0kifs/uipilot/releases/tag/v0.1.0
