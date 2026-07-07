# Presentation layer — the CLI and output renderers.
#
# Turns domain objects into JSON / Rich tables / Playwright-MCP / pw-test / POM
# text. Talks to the application layer for use cases and references domain types
# only for formatting. Nothing depends on this layer.
#
# Components:
#   cli        the Typer entrypoint (console script `uipilot`); parses args,
#              calls application use cases, and formats results.
#   renderers  CompiledScript/model -> json | playwright-mcp | steps | pw-test |
#              pw-pom output strings.
