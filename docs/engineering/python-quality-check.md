---
name: python-quality-check
description: Verify Python application code quality and functionality — run static analysis (ty, ruff, vulture), write/run integration & e2e tests with pytest, and enforce >90% coverage with pytest-cov. Use when asked to check, verify, lint, type-check, test, or measure coverage of Python code.
---

# Python Code Quality & Functionality Verification

Verify a Python app in two passes: **static analysis** (no execution) then **tests + coverage** (execution). Run static checks first — they are fast and catch errors tests can't reach.

Assumes [uv](https://docs.astral.sh/uv/). Prefix commands with `uv run` (or activate the venv). Run every tool from the project root.

## Project setup

Declare the whole toolchain as a dev group so `uv sync --group dev` reproduces it identically for every contributor and CI:

```toml
[project]
requires-python = ">=3.12"         # the Python floor — ruff & ty both read this

[dependency-groups]                # PEP 735 dev deps — not shipped with the package
dev = [
  "ruff",          # lint + format
  "ty",            # type check
  "vulture",       # dead-code detection
  "pytest",        # test runner
  "pytest-cov",    # coverage plugin
  "pytest-xdist",  # parallel test execution (-n auto)
]
```

Each tool's own config (`[tool.ruff]`, `[tool.ty]`, `[tool.vulture]`, `[tool.pytest.ini_options]`, `[tool.coverage.*]`) lives in its section below — all in one `pyproject.toml` as the single source of truth. Pin versions in CI (`uv lock`) so tool upgrades never silently change results.

## Quick sequence

```bash
uv run ruff format --check .   # 1. formatting
uv run ruff check .            # 2. lint
uv run ty check                # 3. type check
uv run vulture . vulture_whitelist.py  # 4. dead code
uv run pytest --cov --cov-branch --cov-fail-under=90  # 5. tests + coverage
```

All five must exit `0`. Any non-zero exit = failure to fix, not to ignore.

---

## 1. Static analysis

### ruff — lint + format (Astral, Rust)

```bash
uv run ruff check .              # lint; exits 1 if issues
uv run ruff check --fix .        # auto-fix safe violations
uv run ruff check --fix --unsafe-fixes .  # include unsafe fixes (review diff)
uv run ruff format .             # format
uv run ruff format --check .     # CI: verify formatted, don't write
```

**Interpreting output:** each line is `path:line:col: CODE message`. The `CODE` prefix names the rule family (`E`/`W` pycodestyle, `F` pyflakes, `I` isort, `B` bugbear, `UP` pyupgrade, `S` bandit-security). Look up a rule: `uv run ruff rule F401`. `F`-codes (undefined/unused names) and `B`-codes (real bugs) matter most — never blanket-ignore them.

Config in `pyproject.toml` (be explicit; avoid `select = ["ALL"]` which changes on upgrade):

```toml
[tool.ruff]
line-length = 100
# omit target-version — Ruff infers it from requires-python (see Project setup) so the two can't drift

[tool.ruff.lint]
# Explicit, incrementally-grown set — never `["ALL"]` (pulls in new rules on upgrade).
select = [
  "F",    # pyflakes — undefined names, unused imports/vars (real bugs; non-negotiable)
  "E",    # pycodestyle errors — style; some overlap the formatter but harmless
  "W",    # pycodestyle warnings — whitespace/deprecation nits
  "I",    # isort — import ordering (auto-fix; ends import bikeshedding)
  "B",    # flake8-bugbear — likely bugs: mutable defaults, silent except, etc.
  "UP",   # pyupgrade — modernize syntax for your Python floor (auto-fix)
  "S",    # flake8-bandit — security: hardcoded secrets, unsafe subprocess/eval
  "C4",   # flake8-comprehensions — cleaner, faster comprehensions (auto-fix)
  "SIM",  # flake8-simplify — collapse redundant/verbose logic
  "RET",  # flake8-return — consistent, minimal return/branch flow
  "PTH",  # flake8-use-pathlib — prefer pathlib over os.path
  "RUF",  # Ruff-native rules — extra correctness checks (e.g. mutable dataclass defaults)
]
[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101"]  # allow `assert` in tests

# Opinionated/noisy families — enable deliberately, one at a time, not by default:
#   N (naming), ANN (annotation coverage), D (docstrings), ERA (commented-out code)
```

**Grow the set incrementally:** add one family, run `ruff check --fix`, review the diff, commit — then add the next. `line-length` is a team convention (88 = Black/Ruff default, 100 also common) — pick one and stay consistent. Never hardcode `target-version` above your real support floor; let it follow `requires-python`.

Suppress one line only with justification: `# noqa: F401  # re-exported`.

### ty — type checker (Astral, Rust)

```bash
uv run ty check                        # check project
uv run ty check src/                   # limit scope
uv run ty check --python-version 3.12  # match requires-python floor
uv run ty check --output-format concise
uv run ty check --error-on-warning     # CI: warnings fail too
```

**Interpreting output:** diagnostics show severity (`error`/`warning`), a rule name (e.g. `invalid-argument-type`, `unresolved-import`), the offending span, and often a hint. Exit `0` = clean. Common real issues: `unresolved-import` (missing dep / wrong venv), `possibly-unbound`, `invalid-return-type`. Point ty at the right env with `--python .venv` if it can't infer it.

Escalate/silence per rule: `--error <rule>`, `--warn <rule>`, `--ignore <rule>`, or inline `# ty: ignore[rule-name]`. Config:

```toml
[tool.ty.rules]
unresolved-import = "error"   # missing dep / wrong venv should fail loudly
```

### vulture — dead code

```bash
uv run vulture src/ vulture_whitelist.py --min-confidence 80
```

**Interpreting output:** `path:line: unused function 'foo' (60% confidence)`. Confidence 60–100%; **100% = certainly dead**. Treat high-confidence hits as removal candidates; verify before deleting (dynamic access via `getattr`, framework hooks, and public API re-exports are false positives).

**False positives:** generate a whitelist once, then re-scan against it:

```bash
uv run vulture src/ --make-whitelist > vulture_whitelist.py
```

The whitelist is real Python simulating usage — commit it. Prefix intentionally-unused args with `_` (e.g. `def cb(_event):`) so vulture skips them. In CI use `--min-confidence 100` to avoid noise, or `--min-confidence 80` in local sweeps. Config (so you don't repeat the flags):

```toml
[tool.vulture]
paths = ["src", "vulture_whitelist.py"]
min_confidence = 80
```

---

## 2. Tests with pytest

### Conventions

Non-negotiable for every tier; a test that breaks one is a defect to fix.

- **AAA structure** — blank-line-separated *arrange* (inputs/state), *act* (the one behavior under test), *assert*. One act per test; a second act means a second test. Share arrange via fixtures.
- **Independence** — no test relies on another's state or order. Set up and tear down via fixtures (`tmp_path`, `yield`); no shared mutable module state. Must give identical results shuffled and under `-n auto`.
- **Naming** — describe what's verified so a failure is legible from the report. Files: unit mirror the module (`test_<module>.py`), integration name the flow (`test_save_then_load.py`), e2e name the entrypoint/command (`test_cli_build.py`); the tier lives in the `tests/{unit,integration,e2e}/` dir, not the filename. Functions `test_<subject>_<scenario>_<expected>` (e.g. `test_compile_missing_ref_raises`) — not `test_1`/`test_it_works`; optional grouping `Test<Subject>`.
- **Every change is tested** — every new/changed feature, bug fix, or other code change lands with at least one unit, one integration, and one e2e test exercising it (new or an updated existing one). A bug fix adds the regression test that would have caught it.
- **Every feature is covered three ways** — happy path, negative (invalid input / expected errors), and edge cases (empty, boundary, limits). One passing case is not coverage.

### Structure

```
tests/
  unit/          # pure logic, no I/O — fast
  integration/   # multiple units together: real DB/filesystem/HTTP-to-local
  e2e/           # full app through its public entrypoint (CLI, API)
conftest.py      # shared fixtures
```

Register markers in `pyproject.toml` so you can run tiers selectively:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
  "unit: pure logic, no I/O",
  "integration: touches real external resources (DB, fs, network)",
  "e2e: exercises the whole app end-to-end",
]
addopts = "-ra --strict-markers"
```

Mark **every** test with its tier — `@pytest.mark.unit`, `@pytest.mark.integration`, or `@pytest.mark.e2e` — exactly one per test, so tier selection is explicit and no test silently escapes a tier filter. `--strict-markers` catches a mistyped tier (fails collection). Run a tier: `uv run pytest -m unit`. Exclude: `uv run pytest -m "not e2e"`.

To tag a whole tier dir, don't use `pytestmark = pytest.mark.<tier>` in its `conftest.py` — it's **silently ignored** there (works only in a test *module*); tests still pass `--strict-markers` yet vanish under `-m <tier>`. Use a path-scoped hook instead:

```python
# tests/unit/conftest.py — tags every test under this dir
_HERE = Path(__file__).parent
def pytest_collection_modifyitems(items):
    for item in items:
        if _HERE in item.path.parents:
            item.add_marker(pytest.mark.unit)
```

That plus `--strict-markers` still misses a test dropped at `tests/` root, outside every tier dir. Catch it with a `trylast` guard (runs after the per-dir hooks) in the **root** `conftest.py`:

```python
# tests/conftest.py — fail collection on any test lacking exactly one tier
_TIERS = {"unit", "integration", "e2e"}
@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items):
    bad = [i.nodeid for i in items if len({m.name for m in i.iter_markers()} & _TIERS) != 1]
    if bad:
        raise pytest.UsageError("need exactly one tier marker:\n  " + "\n  ".join(bad))
```

### Integration tests

Exercise real collaborators, not mocks, but keep them local and deterministic:

- **DB / files:** use `tmp_path` (fixture) or an ephemeral SQLite/Docker service spun up in a fixture; roll back or recreate per test.
- **HTTP:** hit a locally-started test server or use `respx`/`responses` to stub the network boundary — not the code under test.
- Put shared setup in `conftest.py` fixtures; scope expensive ones (`scope="session"`) and yield for teardown.

```python
import pytest

@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    migrate(conn)
    yield conn
    conn.close()

@pytest.mark.integration
def test_save_then_load(db):
    save(db, Item(id=1, name="x"))
    assert load(db, 1).name == "x"
```

### E2E tests

Drive the app through its real entrypoint and assert on observable output/side-effects.

- **CLI:** invoke the actual command in a subprocess (`subprocess.run([...], capture_output=True)`) or via the framework's runner (Click/Typer `CliRunner`). Assert exit code, stdout, and files written.
- **Web API:** use the framework test client (`httpx.AsyncClient` + ASGITransport, FastAPI `TestClient`) against the real app object; assert status + body.

```python
from subprocess import run

@pytest.mark.e2e
def test_cli_build(tmp_path):
    r = run(["myapp", "build", "-o", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0
    assert (tmp_path / "out.json").exists()
```

### Anchor fixture paths to the repo root, not `__file__` depth

`Path(__file__).parent.parent / "fixtures"` breaks the moment a test moves between tier dirs (which the layout above encourages). Walk up to a sentinel instead, so the path survives any nesting:

```python
_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
DEMO = _ROOT / "fixtures" / "demo"
```

### Running

```bash
uv run pytest                    # all
uv run pytest -x -q              # stop at first failure, quiet
uv run pytest -m integration     # one tier
uv run pytest -k "save and not slow"  # by name
uv run pytest -n auto            # parallel (needs pytest-xdist)
```

Read failures bottom-up: the assert diff and traceback show expected vs actual. `-ra` prints a summary of skips/xfails so nothing silently disappears.

---

## 3. Coverage with pytest-cov — enforce >90%

```bash
uv run pytest --cov=myapp --cov-branch --cov-report=term-missing --cov-fail-under=90
```

- `--cov=myapp` — measure the app package (name it explicitly; not tests).
- `--cov-branch` — count both sides of every `if`/`else`. **Use this** — line coverage alone hides untested branches.
- `--cov-report=term-missing` — prints uncovered line numbers in the terminal.
- `--cov-report=html` — writes `htmlcov/index.html` to visually find gaps.
- `--cov-fail-under=90` — process exits non-zero below 90%, failing CI.

Configure once in `pyproject.toml`:

```toml
[tool.coverage.run]
source = ["myapp"]
branch = true
parallel = true          # needed for xdist / subprocess
omit = ["*/tests/*", "*/__main__.py"]

[tool.coverage.report]
fail_under = 90
show_missing = true
skip_covered = true      # list only files with gaps
exclude_lines = [
  "pragma: no cover",
  "raise NotImplementedError",
  "if TYPE_CHECKING:",
  "if __name__ == .__main__.:",
  "@(abc\\.)?abstractmethod",
]
```

**Parallel / subprocess note:** with `-n auto`, xdist, or e2e subprocesses each worker writes its own `.coverage.*`. Set `parallel = true` and combine before reporting so numbers aren't deflated:

```bash
uv run coverage combine && uv run coverage report --fail-under=90
```

### Reaching & keeping >90%

1. Run with `term-missing`; open the file:line ranges it lists.
2. Add tests that execute those lines **and** their branch alternatives — a `# pragma: no cover` only for genuinely unreachable defensive code (log the reason).
3. Coverage proves what code *ran*, not that assertions are meaningful — pair each covered path with a real assertion, not just execution. Prioritize core logic, entrypoints, and error paths over trivial getters.
4. Wire the threshold into CI so regressions block the merge.

---

## Definition of done

- `ruff format --check`, `ruff check`, `ty check`, `vulture` all exit `0`.
- `pytest` green across unit/integration/e2e tiers — including under shuffled order and `-n auto` (proves independence).
- Every test follows AAA structure, is order-independent, and is named per the conventions above.
- The change ships with unit + integration + e2e tests covering happy-path, negative, and edge cases.
- `--cov-fail-under=90` passes with `--cov-branch`.
- Any suppression (`noqa`, `ty: ignore`, `pragma: no cover`, vulture whitelist entry) carries a one-line justification.
