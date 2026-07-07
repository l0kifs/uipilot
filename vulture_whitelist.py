# Vulture whitelist — names that are intentionally "unused" from a pure
# static-reachability view but are part of the engine's public surface.
#
# Regenerate the raw list with:  uvx vulture src --make-whitelist
# Keep this file curated: every entry below is a *deliberate* export, not dead
# code. Genuinely dead code should be deleted, never whitelisted.
#
# This module is never imported at runtime; vulture parses it as an extra source
# so the referenced attributes count as "used".

from uipilot.domain import errors, model
from uipilot.presentation import cli

# --- Public exception hierarchy (raised by callers/adapters, see errors.py) ---
errors.ResolutionError

# --- Documented model vocabulary: enumerations of the legal values a pack may
#     use. They are the spec for pack authors and validation, referenced from
#     docs/tests, not (all) from engine control flow. ---
model.SELECTOR_STRATEGIES
model.PARAM_TYPES
model.STEP_OPS
model.CAPTURE_SOURCES
model.TRANSPORTS
model.API_ROLES

# --- Dataclass fields populated by the YAML loader / consumed by renderers ---
model.Param.enum
model.App.package
model.PathStep.is_subflow

# --- Typer command callbacks: invoked by the Typer framework via decorators,
#     never called directly by our code. ---
cli.main
cli.show_action
cli.show_element
cli.emit
cli.import_md_cmd
