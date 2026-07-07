"""Canonical data model.

These dataclasses carry **no** domain vocabulary — no "operator", "tenant",
"wallet". `risk` values, env-var names, and token keys are all resolved against
the pack's ``flowmap.config.yaml``, so the engine dataclasses are identical
across web apps. The generic term for a UI surface is **app**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------

# Priority mirrors the map convention: role(name) > label > text > css/data-*.
SELECTOR_STRATEGIES = ("role", "label", "text", "css", "testid")


def _js_str(value: str) -> str:
    """Render a Python string as a single-quoted JS string literal."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


@dataclass(frozen=True)
class Selector:
    """A structured, executor-neutral element locator.

    Stored structurally (never as a raw locator string) so the model is
    lintable and re-emittable to a Playwright-MCP element description *or* a
    ``@playwright/test`` locator expression.
    """

    strategy: str
    role: Optional[str] = None
    name: Optional[str] = None
    text: Optional[str] = None
    label: Optional[str] = None
    css: Optional[str] = None
    testid: Optional[str] = None
    # ``scope: dialog`` disambiguates a control that also exists on the page
    # behind a modal (dialog's Create vs a page Create).
    scope: Optional[str] = None
    exact: Optional[bool] = None

    def to_locator(self) -> str:
        """Render to a ``@playwright/test`` locator expression."""
        opts: list[str] = []
        if self.name is not None and self.strategy in ("role", "label", "text"):
            opts.append(f"name: {_js_str(self.name)}")
        if self.exact:
            opts.append("exact: true")
        opts_str = f", {{ {', '.join(opts)} }}" if opts else ""

        if self.strategy == "role":
            base = f"getByRole({_js_str(self.role or '')}{opts_str})"
        elif self.strategy == "label":
            base = f"getByLabel({_js_str(self.label or self.name or '')})"
        elif self.strategy == "text":
            base = f"getByText({_js_str(self.text or self.name or '')})"
        elif self.strategy == "testid":
            base = f"getByTestId({_js_str(self.testid or '')})"
        elif self.strategy == "css":
            base = f"locator({_js_str(self.css or '')})"
        else:  # pragma: no cover - guarded at load time
            base = f"locator({_js_str(self.css or self.name or '')})"

        if self.scope:
            # e.g. getByRole('dialog').getByRole('button', {name:'Create'})
            return f"getByRole({_js_str(self.scope)}).{base}"
        return base

    def describe(self, element_type: Optional[str] = None) -> str:
        """A short human description for a Playwright-MCP ``element`` arg,
        e.g. ``"dialog Create button"``."""
        label = self.name or self.text or self.label or self.css or self.testid or ""
        parts: list[str] = []
        if self.scope:
            parts.append(self.scope)
        if label:
            parts.append(label)
        if element_type and element_type not in label.lower():
            parts.append(element_type)
        return " ".join(parts).strip() or (element_type or "element")

    def signature(self) -> tuple:
        """Identity used to detect ambiguous/duplicate selectors."""
        return (self.strategy, self.role, self.name, self.text, self.label,
                self.css, self.testid, self.scope)

    def as_dict(self) -> dict:
        """Non-null fields as a plain dict, for JSON output and re-emission."""
        out = {}
        for key in ("strategy", "role", "name", "text", "label", "css", "testid", "scope"):
            val = getattr(self, key)
            if val is not None:
                out[key] = val
        if self.exact:
            out["exact"] = True
        return out


# ---------------------------------------------------------------------------
# Elements, params, steps, captures
# ---------------------------------------------------------------------------


@dataclass
class Element:
    id: str
    app: str
    type: str
    selector: Selector
    section: Optional[str] = None
    purpose: Optional[str] = None


PARAM_TYPES = ("string", "enum", "secret", "address", "amount", "int")


@dataclass
class Param:
    key: str
    type: str = "string"
    required: bool = False
    default: Optional[str] = None
    enum: list[str] = field(default_factory=list)

    @property
    def is_secret(self) -> bool:
        return self.type == "secret"


# Step ops and their Playwright-MCP tool mapping (see design §6).
STEP_OPS = (
    "navigate", "snapshot", "click", "fill", "type", "select",
    "press", "wait_for", "expect", "capture", "upload",
)

# Ops that interact with a live element and therefore need a fresh snapshot ref.
INTERACTING_OPS = ("click", "fill", "type", "select", "press", "upload")


@dataclass
class Step:
    op: str
    element: Optional[str] = None
    value: Optional[str] = None
    wait_for: Optional[dict] = None  # {text} | {textGone} | {time}
    scope: Optional[str] = None
    optional: bool = False
    # capture-step fields (a step can also mint a capture inline)
    key: Optional[str] = None
    from_: Optional[str] = None
    pattern: Optional[str] = None
    path: Optional[str] = None
    # free-form extra args (e.g. select values, key name, upload paths)
    args: dict = field(default_factory=dict)


CAPTURE_SOURCES = ("url", "element", "clipboard", "response")


@dataclass
class Capture:
    key: str
    from_: str
    pattern: Optional[str] = None
    path: Optional[str] = None
    element: Optional[str] = None


# ---------------------------------------------------------------------------
# Actions (UI + API)
# ---------------------------------------------------------------------------

TRANSPORTS = ("ui", "api")
API_ROLES = ("setup", "crosscheck")


@dataclass
class Action:
    id: str
    app: str
    transport: str = "ui"
    purpose: str = ""
    risk: str = "low"
    # --- UI-only ---
    route: Optional[str] = None
    elements: list[str] = field(default_factory=list)
    prev: list[str] = field(default_factory=list)
    next: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    # --- API-only ---
    role: Optional[str] = None  # setup | crosscheck
    call: Optional[str] = None  # "factories.tenant:create_tenant"
    # --- both ---
    params: list[Param] = field(default_factory=list)
    captures: list[Capture] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)

    @property
    def is_api(self) -> bool:
        return self.transport == "api"

    @property
    def is_ui(self) -> bool:
        return self.transport == "ui"

    def param(self, key: str) -> Optional[Param]:
        for p in self.params:
            if p.key == key:
                return p
        return None


# ---------------------------------------------------------------------------
# Apps and flows
# ---------------------------------------------------------------------------


@dataclass
class Auth:
    entry_flow: Optional[str] = None
    storage_state_key: Optional[str] = None


@dataclass
class App:
    id: str
    id_prefix: str
    base_url_env: Optional[str] = None
    base_url_default: Optional[str] = None
    package: Optional[str] = None
    auth: Optional[Auth] = None


@dataclass
class PathStep:
    """One entry in a flow ``path``.

    Exactly one of ``action`` or ``use`` is set. ``use`` inlines a subflow (L2);
    ``alias`` (``as:``) namespaces its captures for repeated invocations (L3);
    ``params``/``args`` scope overrides to this invocation.
    """

    action: Optional[str] = None
    use: Optional[str] = None
    alias: Optional[str] = None
    role: Optional[str] = None  # override api role at call site (crosscheck)
    params: dict = field(default_factory=dict)

    @property
    def ref(self) -> str:
        return self.action or self.use or "?"

    @property
    def is_subflow(self) -> bool:
        return self.use is not None


@dataclass
class Flow:
    id: str
    app: Optional[str] = None
    description: str = ""
    path: list[PathStep] = field(default_factory=list)
    params: list[Param] = field(default_factory=list)
    guard: Optional[dict] = None  # cheap expect/wait_for that short-circuits (L4)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class Token:
    key: str
    from_: str  # env | counter
    name: Optional[str] = None
    default: Optional[str] = None


@dataclass
class RiskTaxonomy:
    levels: list[str] = field(default_factory=lambda: ["low", "destructive"])
    gated: list[str] = field(default_factory=lambda: ["destructive"])

    def rank(self, level: str) -> int:
        try:
            return self.levels.index(level)
        except ValueError:
            return -1

    def max(self, levels: list[str]) -> Optional[str]:
        present = [level for level in levels if level in self.levels]
        if not present:
            return levels[0] if levels else None
        return max(present, key=self.rank)


@dataclass
class CapabilitySpec:
    key: str
    impl: str  # "module.path:function"


@dataclass
class Config:
    pack: str
    apps: list[str]
    tokens: dict[str, Token] = field(default_factory=dict)
    risk: RiskTaxonomy = field(default_factory=RiskTaxonomy)
    capabilities: dict[str, CapabilitySpec] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# The loaded pack
# ---------------------------------------------------------------------------


@dataclass
class Pack:
    config: Config
    apps: dict[str, App]
    elements: dict[str, Element]
    actions: dict[str, Action]
    flows: dict[str, Flow]
    root: Path

    # -- convenience lookups -------------------------------------------------

    def app(self, app_id: str) -> Optional[App]:
        return self.apps.get(app_id)

    def action(self, action_id: str) -> Optional[Action]:
        return self.actions.get(action_id)

    def element(self, element_id: str) -> Optional[Element]:
        return self.elements.get(element_id)

    def flow(self, flow_id: str) -> Optional[Flow]:
        return self.flows.get(flow_id)

    def ui_actions(self) -> list[Action]:
        return [a for a in self.actions.values() if a.is_ui]

    def api_actions(self) -> list[Action]:
        return [a for a in self.actions.values() if a.is_api]

    def actions_for_app(self, app_id: str) -> list[Action]:
        return [a for a in self.actions.values() if a.app == app_id]
