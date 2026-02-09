"""Tests for the 1Password vault implementation."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from docketeer_1password.vault import OnePasswordVault


@pytest.fixture()
def vault() -> OnePasswordVault:
    return OnePasswordVault(token="test-sa-token")


def _mock_op(stdout: str = "", returncode: int = 0) -> AsyncMock:
    """Create a mock for asyncio.create_subprocess_exec."""
    proc = AsyncMock()
    proc.communicate.return_value = (stdout.encode(), b"")
    proc.returncode = returncode
    return proc


# --- env ---


async def test_op_receives_service_account_token(vault: OnePasswordVault):
    vaults_json = json.dumps([])

    async def fake_exec(*args: object, **kwargs: object) -> AsyncMock:
        env: dict[str, str] = kwargs.get("env", {})  # type: ignore[assignment]
        assert env["OP_SERVICE_ACCOUNT_TOKEN"] == "test-sa-token"
        assert "PATH" in env
        return _mock_op(vaults_json)

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        await vault.list()


# --- list ---


def _item_detail(fields: list[dict[str, str]]) -> str:
    """Build a JSON item detail response with the given fields."""
    return json.dumps({"fields": fields})


async def test_list_secrets(vault: OnePasswordVault):
    vaults_json = json.dumps([{"id": "abc", "name": "Agent"}])
    items_json = json.dumps(
        [
            {"id": "item1", "title": "api-key"},
            {"id": "item2", "title": "db-cred"},
        ]
    )
    detail1 = _item_detail([{"label": "password", "id": "pw"}])
    detail2 = _item_detail(
        [
            {"label": "username", "id": "un"},
            {"label": "password", "id": "pw"},
        ]
    )

    responses = [vaults_json, items_json, detail1, detail2]
    call_count = 0

    async def fake_exec(*args: object, **_kwargs: object) -> AsyncMock:
        nonlocal call_count
        call_count += 1
        return _mock_op(responses[call_count - 1])

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        refs = await vault.list()

    names = [r.name for r in refs]
    assert "Agent/api-key/password" in names
    assert "Agent/db-cred/username" in names
    assert "Agent/db-cred/password" in names


async def test_list_multiple_vaults(vault: OnePasswordVault):
    vaults_json = json.dumps(
        [
            {"id": "v1", "name": "Vault1"},
            {"id": "v2", "name": "Vault2"},
        ]
    )
    items_v1 = json.dumps([{"id": "i1", "title": "secret-a"}])
    items_v2 = json.dumps([{"id": "i2", "title": "secret-b"}])
    detail_a = _item_detail([{"label": "password", "id": "pw"}])
    detail_b = _item_detail([{"label": "token", "id": "tk"}])

    responses = [vaults_json, items_v1, detail_a, items_v2, detail_b]
    call_count = 0

    async def fake_exec(*args: object, **_kwargs: object) -> AsyncMock:
        nonlocal call_count
        call_count += 1
        return _mock_op(responses[call_count - 1])

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        refs = await vault.list()

    names = {r.name for r in refs}
    assert names == {"Vault1/secret-a/password", "Vault2/secret-b/token"}


async def test_list_empty(vault: OnePasswordVault):
    vaults_json = json.dumps([{"id": "v1", "name": "Agent"}])
    items_json = json.dumps([])

    responses = [vaults_json, items_json]
    call_count = 0

    async def fake_exec(*args: object, **_kwargs: object) -> AsyncMock:
        nonlocal call_count
        call_count += 1
        return _mock_op(responses[call_count - 1])

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        refs = await vault.list()

    assert refs == []


async def test_list_no_vaults(vault: OnePasswordVault):
    vaults_json = json.dumps([])

    async def fake_exec(*args: object, **_kwargs: object) -> AsyncMock:
        return _mock_op(vaults_json)

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        refs = await vault.list()

    assert refs == []


# --- resolve ---


async def test_resolve(vault: OnePasswordVault):
    async def fake_exec(*args: object, **_kwargs: object) -> AsyncMock:
        return _mock_op("sk-abc123\n")

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec) as mock:
        value = await vault.resolve("Agent/api-key/password")

    assert value == "sk-abc123"
    cmd = list(mock.call_args.args)
    assert "--fields" in cmd
    field_idx = cmd.index("--fields")
    assert cmd[field_idx + 1] == "password"


async def test_resolve_custom_field(vault: OnePasswordVault):
    async def fake_exec(*args: object, **_kwargs: object) -> AsyncMock:
        return _mock_op("admin")

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec) as mock:
        value = await vault.resolve("Agent/db-cred/username")

    assert value == "admin"
    cmd = list(mock.call_args.args)
    field_idx = cmd.index("--fields")
    assert cmd[field_idx + 1] == "username"


async def test_resolve_bad_path(vault: OnePasswordVault):
    with pytest.raises(ValueError, match="vault/item/field"):
        await vault.resolve("no-slashes")


async def test_resolve_two_parts(vault: OnePasswordVault):
    with pytest.raises(ValueError, match="vault/item/field"):
        await vault.resolve("Agent/api-key")


async def test_resolve_op_failure(vault: OnePasswordVault):
    async def fake_exec(*args: object, **_kwargs: object) -> AsyncMock:
        proc = _mock_op("", returncode=1)
        proc.communicate.return_value = (b"", b"not found")
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        with pytest.raises(RuntimeError, match="not found"):
            await vault.resolve("Agent/missing/password")


# --- store ---


async def test_store(vault: OnePasswordVault):
    async def fake_exec(*args: object, **_kwargs: object) -> AsyncMock:
        return _mock_op()

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec) as mock:
        await vault.store("Agent/new-secret/password", "my-value")

    cmd = list(mock.call_args.args)
    assert "--vault" in cmd
    assert "Agent" in cmd
    assert "--title" in cmd
    assert "new-secret" in cmd
    assert "password=my-value" in cmd


async def test_store_custom_field(vault: OnePasswordVault):
    async def fake_exec(*args: object, **_kwargs: object) -> AsyncMock:
        return _mock_op()

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec) as mock:
        await vault.store("Agent/db-cred/api_token", "tok-123")

    cmd = list(mock.call_args.args)
    assert "api_token=tok-123" in cmd


async def test_store_bad_path(vault: OnePasswordVault):
    with pytest.raises(ValueError, match="vault/item/field"):
        await vault.store("no-slash", "value")


async def test_store_op_failure(vault: OnePasswordVault):
    async def fake_exec(*args: object, **_kwargs: object) -> AsyncMock:
        proc = _mock_op("", returncode=1)
        proc.communicate.return_value = (b"", b"permission denied")
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        with pytest.raises(RuntimeError, match="permission denied"):
            await vault.store("Agent/secret/password", "value")


# --- generate ---


async def test_generate(vault: OnePasswordVault):
    async def fake_exec(*args: object, **_kwargs: object) -> AsyncMock:
        return _mock_op()

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec) as mock:
        await vault.generate("Agent/random-key/password", length=24)

    cmd = list(mock.call_args.args)
    assert any("24" in str(a) for a in cmd)


async def test_generate_default_length(vault: OnePasswordVault):
    async def fake_exec(*args: object, **_kwargs: object) -> AsyncMock:
        return _mock_op()

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec) as mock:
        await vault.generate("Agent/random-key/password")

    cmd = list(mock.call_args.args)
    assert any("32" in str(a) for a in cmd)


async def test_generate_bad_path(vault: OnePasswordVault):
    with pytest.raises(ValueError, match="vault/item/field"):
        await vault.generate("no-slash")


async def test_generate_op_failure(vault: OnePasswordVault):
    async def fake_exec(*args: object, **_kwargs: object) -> AsyncMock:
        proc = _mock_op("", returncode=1)
        proc.communicate.return_value = (b"", b"error")
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        with pytest.raises(RuntimeError, match="error"):
            await vault.generate("Agent/secret/password")


# --- delete ---


async def test_delete(vault: OnePasswordVault):
    async def fake_exec(*args: object, **_kwargs: object) -> AsyncMock:
        return _mock_op()

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec) as mock:
        await vault.delete("Agent/old-secret/password")

    cmd = list(mock.call_args.args)
    assert "delete" in cmd
    assert "old-secret" in cmd
    assert "--vault" in cmd
    assert "Agent" in cmd


async def test_delete_bad_path(vault: OnePasswordVault):
    with pytest.raises(ValueError, match="vault/item/field"):
        await vault.delete("no-slash")


async def test_delete_op_failure(vault: OnePasswordVault):
    async def fake_exec(*args: object, **_kwargs: object) -> AsyncMock:
        proc = _mock_op("", returncode=1)
        proc.communicate.return_value = (b"", b"not found")
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        with pytest.raises(RuntimeError, match="not found"):
            await vault.delete("Agent/missing/password")
