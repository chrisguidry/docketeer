# Docketeer

Docketeer is a toolkit for building autonomous AI assistants. It's a
[uv workspace](https://docs.astral.sh/uv/concepts/workspaces/) of small,
focused packages that each contribute a piece of the agent: the core engine,
inference backends, chat backends, tool plugins, and task plugins. Everything
is discovered at runtime via standard Python entry points.

Read the [README](README.md) to understand the architecture before diving in.

**These AGENTS.md files are living documents.** If you learn something about
this repo that would have saved you time — a non-obvious pattern, a gotcha, a
convention that isn't written down yet — update the relevant AGENTS.md. They
represent our shared knowledge of how this codebase works.

## Repo structure

This is a flat uv workspace. Every `docketeer-*` directory at the repo root is
an independent Python package with its own `pyproject.toml`, `src/`, and
`tests/`. The `docketeer/` directory (no suffix) is the core package that all
others depend on. Each package has its own AGENTS.md with package-specific
guidance.

Run `uv sync` from the repo root to install everything into one shared venv.

## Quality standards

Everything below is enforced by tooling in pre-commit and CI. These are not
aspirational — they are hard gates. If you skip or work around them, the
commit will be rejected.

### 100% test coverage of both `src/` and `tests/`

Every package requires `--cov-fail-under=100` with branch coverage, measured
over **both** `src/` and `tests/`. This is not negotiable.

Covering `src/` is obvious — every line of production code must be exercised.

Covering `tests/` is just as important. It catches dead test code, unused
helpers, and overly clever test logic with branches that never execute. If your
test file has an `if`, a `try/except`, or a loop that coverage can't fully
trace, that's a sign the test is doing too much. Push complexity into fixtures
or parametrize instead.

When you add production code, you write tests for it. When you delete
production code, you delete the tests that covered it. Coverage doesn't lie —
if you see a gap, something is missing or something is dead.

### File length limits (loq)

[loq](https://github.com/jakekaplan/loq) enforces a **500-line maximum** on all
Python files (`loq.toml` at the repo root). This is checked in pre-commit and
will block your commit if violated.

When a file approaches the limit, **split it**. Extract a module, move helpers
out, break a test file into focused pieces. Do not look for ways to cram more
into a file. The limit exists to keep modules focused and readable. There is
no escape hatch — the answer is always decomposition.

### Type checking, linting, formatting, spelling

ty, ruff, and codespell all run in pre-commit. The configs are in the root
`pyproject.toml` and `.pre-commit-config.yaml` — read them if you're unsure
about a specific rule. The important things to know up front:

- Full type hints are required on all function signatures (test return types
  are the one exception, omitted per ruff config)
- Modern Python 3.12+ syntax: `dict[str, str]` not `Dict[str, str]`,
  `X | None` not `Optional[X]`

## How to run checks

We use **prek**, not pre-commit. prek is a drop-in replacement for
`pre-commit` that runs hooks in parallel. Do not try to use `pre-commit`
directly — it is not installed here.

```sh
# Run all checks (what `git commit` will trigger)
prek run --all-files

# Run a specific check while iterating
prek run ruff --all-files
prek run ty                   # very useful for fixing type errors
prek run loq --all-files
prek run pytest-docketeer     # run tests for just the core package
prek run pytest-docketeer-web # run tests for a specific plugin
```

Each package's tests can also be run directly — `cd` into the package
directory and run the tool:

```sh
cd docketeer-web && pytest              # run all tests for a package
cd docketeer-web && pytest -x           # stop on first failure
cd docketeer-web && pytest -k test_search
cd docketeer-web && ty check            # type-check a single package
```

**Do not use `uv run` to run tools.** It can destroy and recreate the
venv, breaking every other tool in the session and conflicting with
other agents working concurrently.

The `./run-tests` script at the repo root is a shortcut that runs pytest
across all workspace packages sequentially.

## Testing philosophy

Tests have a **1-second timeout** per test. Every test. No exceptions. This
means all I/O must be faked — no network calls, no disk I/O outside of
`tmp_path`, no sleeping. If a test needs to wait for something, the design is
wrong.

### Write flat, simple tests

Tests are covered by the same 100% coverage rule as production code. This
means test files themselves must have no dead branches. Concretely:

- **No `if` statements in tests.** If you need conditional logic, you need
  two tests or a parametrize.
- **No `try`/`except`/`finally` in tests.** Use `pytest.raises` as a context
  manager, or handle cleanup in fixtures.
- **Minimize loops in tests.** If you're looping to check multiple things,
  consider parametrize. If you're looping to build data, put it in a fixture.

Push all setup and teardown complexity into fixtures. Tests should be short,
flat sequences: arrange with fixtures, act, assert.

### Fixtures over mocks

If you find yourself writing the same `MagicMock()` construction in more
than one test, stop and make it a fixture or a factory function in
`conftest.py`. Common smells:

- **Duplicated helpers across test files.** If two test files define the
  same helper, it belongs in conftest. Don't copy-paste between files.
- **Deep `MagicMock()` chains.** Building `mock.choices[0].delta.content`
  by hand in every test is noisy and fragile. Write a small builder
  function (`make_chunk(content="Hello", finish_reason="stop")`) and put
  it in conftest.
- **Repeated `with patch(...)` blocks.** If every test in a file patches
  the same thing, that's a fixture. Use `@pytest.fixture(autouse=True)`
  or a yielding fixture that provides the mock.
- **`# pragma: no cover` on test helpers.** This means the helper is dead
  code. Every conftest helper must be exercised by at least one test. If
  coverage can't reach it, something is wrong — either the helper is
  unused or tests are importing local copies instead of the conftest one.

Prefer the narrowest mock that works. If a protocol has a test double in
`docketeer.testing`, use that instead of `MagicMock`. If you're mocking a
dataclass, construct the real dataclass. Only reach for `MagicMock` when
you genuinely need a stand-in for something you can't easily construct.

### Use the test doubles in `docketeer.testing`

The core package provides `MemoryChat`, `MemoryVault`, and related test
doubles in `docketeer.testing`. These are purpose-built in-memory
implementations of the `ChatClient` and `Vault` protocols. Use them instead
of writing your own mocks for these interfaces.

### Every package is independent

Each package runs its own pytest with its own coverage. When working on a
plugin, run that plugin's tests from its directory. The plugin depends on the
core `docketeer` package, so changes to core types can break downstream — run
the affected plugin tests too.

## Plugin patterns

All plugins register via entry points in their `pyproject.toml`. The patterns:

- **Single-select** (`docketeer.chat`, `docketeer.executor`,
  `docketeer.vault`, `docketeer.inference`): one active at a time, auto-selected
  if only one is installed.
- **Multi-load** (`docketeer.tools`, `docketeer.prompt`, `docketeer.tasks`):
  everything installed gets loaded.

Tool plugins register by importing their tool-decorated functions in their
package's `__init__.py`. The `@registry.tool()` decorator on a function is
what makes it available to the agent.

## Git discipline

- Always `git add .` before committing
- Never amend commits or use `--no-verify`
- If prek fixes files on commit (ruff formatting, etc.), just commit again
- Keep commits and PRs small and focused
