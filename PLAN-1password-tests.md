# Plan: Clean up docketeer-1password test suite

**This is a temporary plan file. Delete it when the work is done.**

## Problem summary

`test_vault.py` repeats a subprocess-mocking pattern in nearly every test.
Each test defines its own `fake_exec` async function that wraps `_mock_op`,
and many use a `nonlocal call_count` counter to return different responses
on successive calls. This is a fixture waiting to happen.

## The repeated pattern

Most tests look like:

```python
async def test_something(vault: OnePasswordVault):
    responses = [first_json, second_json]
    call_count = 0

    async def fake_exec(*args, **_kwargs):
        nonlocal call_count
        call_count += 1
        return _mock_op(responses[call_count - 1])

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        result = await vault.some_method(...)
```

The `fake_exec` closure, the `call_count`, and the
`patch("asyncio.create_subprocess_exec", ...)` are all boilerplate.

## Step 1: Add a fixture that handles subprocess sequencing

Add a fixture to the test file (or create a conftest.py) that patches
`asyncio.create_subprocess_exec` and accepts a sequence of responses:

```python
@pytest.fixture()
def op_cli(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Set up a sequence of `op` CLI responses.

    Usage:
        def test_something(vault, op_cli):
            op_cli("first response", "second response")
            result = await vault.list_secrets()
    """
    responses: list[tuple[str, int]] = []
    call_index = 0

    def setup(*outputs: str, returncodes: list[int] | None = None) -> None:
        nonlocal responses, call_index
        call_index = 0
        codes = returncodes or [0] * len(outputs)
        responses.extend(zip(outputs, codes))

    async def fake_exec(*args: object, **kwargs: object) -> AsyncMock:
        nonlocal call_index
        stdout, returncode = responses[call_index]
        call_index += 1
        return _mock_op(stdout, returncode)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    return setup
```

This keeps `_mock_op` as the low-level builder (it's fine) but eliminates
the per-test `fake_exec` + `call_count` boilerplate.

## Step 2: Rewrite tests to use the fixture

A test like `test_list_secrets` currently builds 4 response strings and a
`call_count` closure. With the fixture:

```python
async def test_list_secrets(vault: OnePasswordVault, op_cli):
    op_cli(vaults_json, items_json, detail1, detail2)
    refs = await vault.list_secrets()
    names = [r.name for r in refs]
    assert "Agent/api-key/password" in names
```

For tests that need to verify the exact command that was called (like
`test_resolve` which checks `--fields` in the args), they can still use
`patch` directly since they need access to the mock object's `call_args`.
OR the fixture can also expose the captured calls.

Alternative design that also captures calls:

```python
@dataclass
class OPFixture:
    calls: list[tuple]  # captured (args, kwargs) from each call

    def __call__(self, *outputs: str, returncodes: list[int] | None = None) -> None:
        ...
```

## Step 3: Handle the env token assertion test

`test_op_receives_service_account_token` needs to inspect `kwargs["env"]`
inside the fake exec. This test can either:
- Keep its own `fake_exec` (it's the only one that checks env)
- Use the fixture if it exposes captured `kwargs`

The simplest approach: make the fixture capture args and kwargs so any test
can inspect them.

## Step 4: Handle failure response tests

Tests like `test_resolve_op_failure` and `test_store_creates_when_item_missing`
pass non-zero returncodes. The fixture should support this via the
`returncodes` parameter. For `test_store_creates_when_item_missing`, the
pattern is: first call fails (returncode=1), second call succeeds
(returncode=0). The fixture should handle:

```python
op_cli("", vaults_json, returncodes=[1, 0])
```

Or:

```python
op_cli(("", 1), (success_json, 0))  # tuples of (stdout, returncode)
```

Pick whichever reads more clearly.

## Validation

```sh
uv run --directory docketeer-1password pytest
prek run loq --all-files
```

Coverage must stay at 100%.
