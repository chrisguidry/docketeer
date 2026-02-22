# Plan: Clean up docketeer-deepinfra test suite

**This is a temporary plan file. Delete it when the work is done.**

## Problem summary

This package has no `conftest.py`. Test infrastructure is duplicated across
files, and nearly every test builds OpenAI response objects from long chains
of `MagicMock()` calls. The result is verbose, fragile tests where the
setup noise drowns out what's actually being tested.

## Step 1: Create `docketeer-deepinfra/tests/conftest.py`

Move all shared infrastructure here. The following are duplicated across
`test_loop_stream.py`, `test_loop_agentic.py`, and `test_loop_usage.py`:

### `AsyncStreamWrapper` class (duplicated 3x, identical each time)

```python
class AsyncStreamWrapper:
    def __init__(self, chunks: list[MagicMock]) -> None:
        self.chunks = list(chunks)
        self._index = 0

    def __aiter__(self) -> "AsyncStreamWrapper":
        return self

    async def __anext__(self) -> MagicMock:
        if self._index >= len(self.chunks):
            raise StopAsyncIteration
        chunk = self.chunks[self._index]
        self._index += 1
        return chunk
```

### `make_stream_mock` function (duplicated 3x, identical)

```python
def make_stream_mock(chunks: list[MagicMock]) -> AsyncMock:
    return AsyncMock(return_value=AsyncStreamWrapper(chunks))
```

### `MODEL` constant (duplicated in every file)

```python
MODEL = InferenceModel(
    model_id="meta-llama/Llama-3.3-70B-Instruct", max_output_tokens=64_000
)
```

### `tool_context` fixture (defined inline in 3 files)

Defined separately in `test_loop_agentic.py`, `test_loop_execute.py`, and
`test_loop_callbacks.py`, all identical:

```python
@pytest.fixture()
def tool_context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace=tmp_path, username="test-user")
```

## Step 2: Add chunk/response builder functions to conftest.py

The core problem is that every test builds OpenAI response structures
manually with deeply nested MagicMock chains. For example, this pattern
appears in nearly every test:

```python
chunk = MagicMock()
chunk.choices = [MagicMock()]
chunk.choices[0].delta = MagicMock()
chunk.choices[0].delta.content = "Hello"
chunk.choices[0].delta.tool_calls = None
chunk.choices[0].finish_reason = "stop"
chunk.usage = None
```

Replace this with builder functions. Suggested API:

```python
def make_chunk(
    content: str | None = None,
    finish_reason: str | None = None,
    tool_calls: list | None = None,
    usage: CompletionUsage | None = None,
) -> MagicMock:
    """Build a single streaming chunk."""
    ...

def make_tool_call(
    index: int = 0,
    call_id: str = "call_1",
    name: str = "test_tool",
    arguments: str = "{}",
) -> MagicMock:
    """Build a tool call delta for a streaming chunk."""
    ...

def make_usage(
    prompt_tokens: int = 100,
    completion_tokens: int = 10,
    total_tokens: int = 110,
    cached_tokens: int | None = None,
) -> CompletionUsage:
    """Build a CompletionUsage, optionally with cached token details."""
    ...
```

Also add a helper that builds a complete mock response (not a streaming
chunk) for tests that mock `stream_message` directly:

```python
def make_response(
    content: str | None = None,
    finish_reason: str = "stop",
    tool_calls: list | None = None,
    usage: MagicMock | None = None,
) -> MagicMock:
    """Build a complete (non-streaming) chat completion response."""
    ...
```

And a convenience for the mock client:

```python
@pytest.fixture()
def mock_client() -> MagicMock:
    """An OpenAI client mock with chat.completions.create pre-wired."""
    client = MagicMock()
    client.chat.completions.create = AsyncMock()
    return client
```

## Step 3: Rewrite `test_loop_stream.py`

This file currently has 10 tests, almost all following the same pattern:
build chunks → make_stream_mock → call stream_message → assert.

With the builders, a test like `test_basic_content_accumulation` goes from
~20 lines of MagicMock construction to roughly:

```python
async def test_basic_content_accumulation(mock_client: MagicMock):
    mock_client.chat.completions.create = make_stream_mock([
        make_chunk(content="Hello "),
        make_chunk(content="world", finish_reason="stop"),
    ])

    result = await stream_message(
        client=mock_client, model=MODEL, system=[], messages=[...],
        tools=[], on_first_text=None, default_model="test-model",
    )
    assert result.choices[0].message.content == "Hello world"
```

Apply this pattern to all 10 tests. Remove all local `MagicMock()` chunk
construction.

## Step 4: Rewrite `test_loop_usage.py`

Same transformation as Step 3. This file has 4 tests. The `make_usage`
builder handles the `CompletionUsage` construction that's currently done
inline with imports and manual construction.

Remove the local `AsyncStreamWrapper`, `make_stream_mock`, and `MODEL`
definitions.

## Step 5: Rewrite `test_loop_agentic.py`

This file has the most complex tests. Key changes:

1. Remove local `AsyncStreamWrapper`, `make_stream_mock`, `MODEL`,
   `tool_context` — all come from conftest now.

2. The `test_tool_round_limit_triggers_summary` test (~50 lines) uses a
   `call_count` list and `side_effect` to return different responses on
   successive calls. This is fine as a pattern, but the chunk construction
   should use the builders.

3. There are three nearly-identical `test_tool_round_limit_triggers_summary*`
   variants that differ only in how `prompt_tokens_details` is set on the
   summary response. After switching to `make_usage`, the variation should
   be expressed through the builder's `cached_tokens` parameter.

4. The `test_tool_call_then_final_response` test has deeply nested
   `with patch(...): with patch(...):` blocks. Consider a fixture:

   ```python
   @pytest.fixture()
   def patched_loop():
       """Patch stream_message and execute_tools for agentic_loop tests."""
       with (
           patch("docketeer_deepinfra.loop.stream_message", new_callable=AsyncMock) as mock_stream,
           patch("docketeer_deepinfra.loop.execute_tools", new_callable=AsyncMock) as mock_exec,
       ):
           yield mock_stream, mock_exec
   ```

## Step 6: Rewrite `test_loop_execute.py`

4 tests, each building a `MagicMock()` tool call. Replace with
`make_tool_call` from conftest (or adapt — the tool calls in execute_tools
are complete objects, not deltas, so the builder may need a variant or the
same one may work).

Remove local `tool_context` fixture.

## Step 7: Rewrite `test_loop_callbacks.py`

1 large test. Same transformation: use conftest fixtures and builders.
Remove local `tool_context` fixture and `MODEL` constant.

The test constructs ~10 MagicMocks inline to build a tool response followed
by a final response. With the builders + `patched_loop` fixture from Step 5,
this should shrink significantly.

## Step 8: Rewrite `test_loop_build.py`

6 tests with a local `_response` helper. This is actually not bad — the
helper is small and focused. But it could use `make_response` from conftest
instead to stay consistent. Low priority within this plan.

## Step 9: Review `test_loop_serialize.py`

This file is organized as test classes with inline imports. The tests
themselves are fine — they're small and focused. The `MagicMock` usage here
is minimal (just `TestToolToDict`). Leave mostly alone, just verify it uses
conftest `MODEL` if applicable.

## Step 10: Review `test_api_backend.py` and `test_init.py`

`test_api_backend.py` has its own `mock_client`, `backend`, and
`tool_context` fixtures. The `mock_client` and `tool_context` could come
from conftest (the `backend` fixture is specific to this file and should
stay). Low priority.

`test_init.py` is fine as-is.

## Validation

After each step, run:

```sh
uv run --directory docketeer-deepinfra pytest
```

Coverage must stay at 100% with branch coverage. If any `pragma: no cover`
markers are needed on conftest helpers, that's a sign something is wrong —
every helper should be exercised by the tests that use it.

Also run loq to make sure no file exceeds 500 lines:

```sh
prek run loq --all-files
```
