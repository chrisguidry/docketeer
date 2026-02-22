# Plan: Clean up docketeer-mcp test suite

**This is a temporary plan file. Delete it when the work is done.**

## Problem summary

Two issues: (1) fixtures are duplicated across 5 test files instead of
living in conftest.py, and (2) `test_oauth.py` repeats the same httpx
client mock construction 14 times.

## Part A: Move shared fixtures to conftest.py

### Duplicated fixtures

The following are defined identically in multiple test files:

**`fresh_manager`** — in `test_tools.py`, `test_tools_oauth.py`,
`test_tools_oauth_edge_cases.py`, `test_prompt.py` (4 copies):

```python
@pytest.fixture(autouse=True)
def fresh_manager() -> Generator[MCPClientManager]:
    fresh = MCPClientManager()
    with (
        patch("docketeer_mcp.tools.manager", fresh),
        patch("docketeer_mcp.prompt.manager", fresh),
    ):
        yield fresh
```

**`data_dir`** — in `test_config.py`, `test_tools.py`, `test_tools_oauth.py`,
`test_tools_oauth_edge_cases.py`, `test_prompt.py` (5 copies):

```python
@pytest.fixture()
def data_dir(tmp_path: Path) -> Generator[Path]:
    d = tmp_path / "data"
    d.mkdir()
    with patch("docketeer_mcp.config.environment") as mock_env:
        mock_env.DATA_DIR = d
        yield d
```

**`mcp_dir`** — in `test_config.py`, `test_tools.py`, `test_tools_oauth.py`,
`test_tools_oauth_edge_cases.py`, `test_prompt.py` (5 copies):

```python
@pytest.fixture()
def mcp_dir(data_dir: Path) -> Path:
    d = data_dir / "mcp"
    d.mkdir()
    return d
```

**`_write_server`** — in `test_tools.py`, `test_tools_oauth.py`,
`test_tools_oauth_edge_cases.py` (3 copies):

```python
def _write_server(mcp_dir: Path, name: str, data: dict) -> None:
    (mcp_dir / f"{name}.json").write_text(json.dumps(data))
```

### Step 1: Move all four to conftest.py

The existing conftest.py already has `_isolated_data_dir`, `workspace`, and
`tool_context`. Add `fresh_manager`, `data_dir`, `mcp_dir`, and
`_write_server` to it.

Note: `fresh_manager` is `autouse=True`. Moving it to conftest will make it
apply to ALL tests in the package. Check that `test_config.py`,
`test_manager.py`, `test_oauth.py`, `test_transport.py`, and `test_tasks.py`
are not broken by having a fresh manager injected. If they are, make it
non-autouse in conftest and add it explicitly to the files that need it.

`_write_server` is a plain helper function, not a fixture. Move it to
conftest and import it in the test files that use it.

### Step 2: Remove duplicates from test files

Delete the local definitions of `fresh_manager`, `data_dir`, `mcp_dir`,
and `_write_server` from all 5 test files. Verify each file still works.

Run after each file:
```sh
uv run --directory docketeer-mcp pytest
```

## Part B: Extract httpx mock fixture for test_oauth.py

### The repeated pattern

Every async test in `test_oauth.py` (14 tests) builds this:

```python
mock_client = AsyncMock()
mock_client.get = mock_get   # or .post = mock_post
mock_client.__aenter__ = AsyncMock(return_value=mock_client)
mock_client.__aexit__ = AsyncMock(return_value=None)

with patch("docketeer_mcp.oauth.httpx.AsyncClient", return_value=mock_client):
    ...
```

The only variation is whether `.get` or `.post` is assigned, and what the
response function does.

### Step 3: Add an httpx mock fixture

Add a fixture to conftest.py (or a local conftest in the test directory)
that patches `httpx.AsyncClient` and provides a way to set response
sequences. Suggested design:

```python
@dataclass
class MockHTTP:
    """Test double for httpx.AsyncClient with response sequencing."""
    client: AsyncMock
    _responses: list[httpx.Response] = field(default_factory=list)

    def set_responses(self, *responses: httpx.Response) -> None:
        self._responses = list(responses)

    # The client.get and client.post will return responses in order
```

Or simpler — just a fixture that yields the mock client already patched:

```python
@pytest.fixture()
def mock_http() -> Generator[AsyncMock]:
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    with patch("docketeer_mcp.oauth.httpx.AsyncClient", return_value=mock_client):
        yield mock_client
```

Then tests just set `.get` or `.post` on the yielded mock:

```python
async def test_discover_with_prm_and_oasm(mock_http: AsyncMock):
    responses = iter([prm_response, oasm_response])
    mock_http.get = lambda url, **kw: anext(responses)

    auth_ep, token_ep, reg_ep, scopes = await discover_oauth_metadata(...)
    assert auth_ep == "https://auth.example.com/authorize"
```

The `_mock_response` helper function at the top of `test_oauth.py` is good
and should stay (or move to conftest if other files need it).

### Step 4: Rewrite test_oauth.py tests

Replace the inline mock construction in all 14 tests with the `mock_http`
fixture. Each test should shrink by 5-6 lines.

### Step 5: Check test_tools_oauth.py

`test_tools_oauth.py` also has 3 instances of the same httpx mock pattern
(for `test_check_auth_required_*` tests). If the fixture works for these
too, use it. These patch `docketeer_mcp.tools.httpx.AsyncClient` rather
than `docketeer_mcp.oauth.httpx.AsyncClient`, so the fixture may need to
accept the patch target as a parameter, or these 3 tests can just stay
as-is since they're a different module.

## Validation

```sh
uv run --directory docketeer-mcp pytest
prek run loq --all-files
```

Coverage must stay at 100%.
