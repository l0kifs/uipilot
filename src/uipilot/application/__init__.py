# Application layer — use-case orchestration.
#
# Wires infrastructure (loading, importing, capability resolution) to domain
# services (compile, validate, verify, pathfind, usage) and returns domain
# objects or plain data — never rendered strings. Imported by presentation;
# imports domain + infrastructure.
#
# Components:
#   service   PackContext plus one function per use case: open_pack,
#             compile_script, validate_pack, verify, route, uses,
#             filter_actions/filter_elements, list_capabilities, import_markdown.
