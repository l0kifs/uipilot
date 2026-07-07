# uipilot — app-agnostic UI-flow engine.
#
# Loads a per-app *pack* (structured YAML + a small config), walks the UI flow
# graph, substitutes params, and emits Playwright-MCP-executable scripts. The
# engine ships no domain vocabulary: everything project-specific (apps, elements,
# actions, flows, risk taxonomy, auth capabilities) lives in a pack.
#
# The code is split into four layers, with dependencies pointing strictly inward
# (presentation -> application -> {domain, infrastructure} -> domain):
#
#   domain/          pure model + business rules (no I/O, no frameworks)
#   infrastructure/  YAML loading, dynamic imports, file I/O
#   application/     use-case orchestration
#   presentation/    the `uipilot` CLI and output renderers
#
# There is intentionally no code here: this file only marks the directory as a
# package. Import concrete symbols from their owning module, e.g.
#   from uipilot.infrastructure.pack_loader import load_pack
#   from uipilot.application.service import open_pack
#   from uipilot.domain.model import Action, Flow, Selector
#
# The distribution version is declared in pyproject.toml (single source).
