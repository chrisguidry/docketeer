# Plan: Clean up docketeer-anthropic test suite

**This is a temporary plan file. Delete it when the work is done.**

## Problem summary

The conftest.py defines helpers (`make_response`, `make_text_block`,
`make_tool_block`, `FakeStream`) that are then **duplicated** into 5
individual test files. The conftest copies are all marked
`# pragma: no cover`, meaning they're dead code that exists only to
satisfy imports that never happen — the test files use their own local
copies instead.

The `FakeStream` class is duplicated 4 times (conftest + 3 test files),
`make_response` 5 times, `make_text_block` 4 times, `make_tool_block`
3 times.

## Affected files

- `conftest.py` — has all helpers marked `# pragma: no cover`
- `test_loop_agentic.py` — duplicates `make_text_block`, `make_tool_block`,
  `make_response`, `FakeStream`, `MODEL`
- `test_stream_message.py` — duplicates `make_text_block`, `make_response`,
  `FakeStream`, `MODEL`
- `test_build_reply.py` — duplicates `make_text_block`, `make_response`,
  `MODEL`
- `test_execute_tools.py` — duplicates `make_tool_block`
- `test_api_backend.py` — duplicates `make_response` (different shape, see
  note below)

## Step 1: Audit conftest.py helpers

Remove every `# pragma: no cover` marker from conftest.py. Run coverage:

```sh
uv run --directory docketeer-anthropic pytest
```

This will likely show the conftest helpers as uncovered, confirming they're
dead code — no test file imports from conftest, they all use local copies.

## Step 2: Delete local duplicates, import from conftest

In each test file, remove the locally-defined copies of `make_response`,
`make_text_block`, `make_tool_block`, and `FakeStream`. Import them from
conftest instead (pytest makes conftest fixtures and top-level names
available automatically, but for plain functions you'll need explicit
imports from `conftest`).

Files to update:
- `test_loop_agentic.py` — remove local `make_text_block`, `make_tool_block`,
  `make_response`, `FakeStream`, `MODEL`. Import from conftest.
- `test_stream_message.py` — remove local `make_text_block`, `make_response`,
  `FakeStream`, `MODEL`. Import from conftest.
- `test_build_reply.py` — remove local `make_text_block`, `make_response`,
  `MODEL`. Import from conftest.
- `test_execute_tools.py` — remove local `make_tool_block`. Import from
  conftest.

## Step 3: Handle `test_api_backend.py` carefully

This file has its own `make_response` that builds a **different shape** —
it's an Anthropic API response mock for the `api_backend.py` module, not
the loop. Check whether the conftest `make_response` works here or if this
one needs to stay local (or be added to conftest under a different name).

It also has `make_text_block` and `make_tool_block` functions that may
match the conftest versions — verify and deduplicate if identical.

## Step 4: Make `MODEL` a conftest-level constant

`MODEL` is defined identically in conftest.py and 4 test files:

```python
MODEL = InferenceModel(model_id="claude-sonnet-4-5-20251001", max_output_tokens=64_000)
```

Keep it in conftest.py only. Test files should import it:

```python
from conftest import MODEL
```

Or, if preferred, make it a fixture. But a plain constant import is simpler
for something that never changes.

## Step 5: Verify FakeStream coverage

After deduplication, `FakeStream` will only exist in conftest.py. Verify
that its methods are all exercised by the tests that use it. The
`_make_text_stream` method has a conditional (`if hasattr(block, "text")`)
that needs to be covered — ensure at least one test passes a response with
a non-text block (like a tool use block) through the stream.

If `FakeStream._make_text_stream` has branches that no test exercises, add
a small test or adjust the class.

## Step 6: Check `mock_client` fixture

conftest.py defines a `mock_client` fixture. Check if test files that build
their own `mock_client` inline could use the fixture instead. Files that do
inline mock client construction:

- `test_stream_message.py` — builds `mock_client` in every test
- `test_loop_agentic.py` — builds `mock_client` in every test

If the conftest fixture works for these, use it. If they need different
wiring (e.g., `messages.stream.return_value`), the fixture could accept
the stream response as a parameter or the tests can continue to build
inline — that's less important than the helper deduplication.

## Validation

After all changes:

```sh
uv run --directory docketeer-anthropic pytest
```

Coverage must be 100% with no `# pragma: no cover` markers on any conftest
helper. Every helper function and every branch of `FakeStream` must be
exercised by at least one test.

Also run:
```sh
prek run loq --all-files
```
