# Domain layer — pure model + business rules.
#
# No I/O, no frameworks. Depends on nothing outside the standard library; every
# other layer depends inward on this one.
#
# Components:
#   model         entities: App, Element, Action, Flow, Step, Param, Capture,
#                 Selector, Config, Pack (and the risk taxonomy).
#   templating    RuntimeContext + {{token}}/{{param}} resolution (env injected).
#   flows         subflow expansion — the single source of truth for inlining
#                 `use:` references, aliasing, and the one-level nesting cap.
#   graph         BFS pathfinding + reachability over UI-action next/prev edges.
#   validation    the static linter (E_/W_ codes): "is the map self-consistent?"
#   compiler      flow/path/actions -> CompiledScript (the payload build).
#   verification  read-only drift-probe builder: "does it still match the UI?"
#   usage         reverse index — change blast radius for an element/action/flow.
#   errors        the shared exception hierarchy.
