"""Tests for the 1Password vault implementation."""

import json
from typing import cast

import pytest

from docketeer_1password.vault import OnePasswordVault

from .helpers import OpCLI, OpResponse


@pytest.fixture()
def op_cli(monkeypatch: pytest.MonkeyPatch) -> OpCLI:
    cli = OpCLI()
    monkeypatch.setattr("asyncio.create_subprocess_exec", cli.exec)
    return cli


@pytest.fixture()
def vault() -> OnePasswordVault:
    return OnePasswordVault(token="test-sa-token")


def _item_detail(fields: list[dict[str, str]]) -> str:
    """Build a JSON item detail response with the given fields."""
    return json.dumps({"fields": fields})


# --- env ---


async def test_op_receives_service_account_token(
    vault: OnePasswordVault, op_cli: OpCLI
):
    op_cli(json.dumps([]))
    await vault.list_secrets()

    env = cast(dict[str, str], op_cli.calls[0].kwargs.get("env", {}))
    assert env["OP_SERVICE_ACCOUNT_TOKEN"] == "test-sa-token"
    assert "PATH" in env


# --- list ---


async def test_list_secrets(vault: OnePasswordVault, op_cli: OpCLI):
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

    op_cli(vaults_json, items_json, detail1, detail2)
    refs = await vault.list_secrets()

    names = [r.name for r in refs]
    assert "Agent/api-key/password" in names
    assert "Agent/db-cred/username" in names
    assert "Agent/db-cred/password" in names


async def test_list_multiple_vaults(vault: OnePasswordVault, op_cli: OpCLI):
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

    op_cli(vaults_json, items_v1, detail_a, items_v2, detail_b)
    refs = await vault.list_secrets()

    names = {r.name for r in refs}
    assert names == {"Vault1/secret-a/password", "Vault2/secret-b/token"}


async def test_list_empty(vault: OnePasswordVault, op_cli: OpCLI):
    vaults_json = json.dumps([{"id": "v1", "name": "Agent"}])
    items_json = json.dumps([])

    op_cli(vaults_json, items_json)
    refs = await vault.list_secrets()

    assert refs == []


async def test_list_no_vaults(vault: OnePasswordVault, op_cli: OpCLI):
    op_cli(json.dumps([]))
    refs = await vault.list_secrets()

    assert refs == []


# --- resolve ---


async def test_resolve(vault: OnePasswordVault, op_cli: OpCLI):
    op_cli("sk-abc123\n")
    value = await vault.resolve("Agent/api-key/password")

    assert value == "sk-abc123"
    cmd = list(op_cli.calls[0].args)
    assert "--fields" in cmd
    field_idx = cmd.index("--fields")
    assert cmd[field_idx + 1] == "password"


async def test_resolve_custom_field(vault: OnePasswordVault, op_cli: OpCLI):
    op_cli("admin")
    value = await vault.resolve("Agent/db-cred/username")

    assert value == "admin"
    cmd = list(op_cli.calls[0].args)
    field_idx = cmd.index("--fields")
    assert cmd[field_idx + 1] == "username"


async def test_resolve_bad_path(vault: OnePasswordVault):
    with pytest.raises(ValueError, match="vault/item/field"):
        await vault.resolve("no-slashes")


async def test_resolve_two_parts(vault: OnePasswordVault):
    with pytest.raises(ValueError, match="vault/item/field"):
        await vault.resolve("Agent/api-key")


async def test_resolve_op_failure(vault: OnePasswordVault, op_cli: OpCLI):
    op_cli(OpResponse(stderr="not found", returncode=1))
    with pytest.raises(RuntimeError, match="not found"):
        await vault.resolve("Agent/missing/password")


# --- store ---


async def test_store_edits_existing_item(vault: OnePasswordVault, op_cli: OpCLI):
    op_cli("")
    await vault.store("Agent/new-secret/password", "my-value")

    cmd = list(op_cli.calls[0].args)
    assert cmd[1] == "item"
    assert cmd[2] == "edit"
    assert "new-secret" in cmd
    assert "--vault" in cmd
    assert "Agent" in cmd
    assert "password=my-value" in cmd


async def test_store_creates_when_item_missing(vault: OnePasswordVault, op_cli: OpCLI):
    op_cli(OpResponse(stderr="not found", returncode=1), "")
    await vault.store("Agent/new-secret/password", "my-value")

    assert len(op_cli.calls) == 2
    first_cmd = list(op_cli.calls[0].args)
    assert first_cmd[2] == "edit"

    second_cmd = list(op_cli.calls[1].args)
    assert second_cmd[2] == "create"
    assert "--vault" in second_cmd
    assert "Agent" in second_cmd
    assert "--title" in second_cmd
    assert "new-secret" in second_cmd
    assert "password=my-value" in second_cmd


async def test_store_custom_field(vault: OnePasswordVault, op_cli: OpCLI):
    op_cli("")
    await vault.store("Agent/db-cred/api_token", "tok-123")

    cmd = list(op_cli.calls[0].args)
    assert "api_token=tok-123" in cmd


async def test_store_bad_path(vault: OnePasswordVault):
    with pytest.raises(ValueError, match="vault/item/field"):
        await vault.store("no-slash", "value")


async def test_store_op_failure(vault: OnePasswordVault, op_cli: OpCLI):
    failure = OpResponse(stderr="permission denied", returncode=1)
    op_cli(failure, failure)
    with pytest.raises(RuntimeError, match="permission denied"):
        await vault.store("Agent/secret/password", "value")


# --- generate ---


async def test_generate_edits_existing_item(vault: OnePasswordVault, op_cli: OpCLI):
    op_cli("")
    await vault.generate("Agent/random-key/password", length=24)

    cmd = list(op_cli.calls[0].args)
    assert cmd[1] == "item"
    assert cmd[2] == "edit"
    assert "random-key" in cmd
    assert "--vault" in cmd
    assert "Agent" in cmd
    assert any("24" in str(a) for a in cmd)


async def test_generate_creates_when_item_missing(
    vault: OnePasswordVault, op_cli: OpCLI
):
    op_cli(OpResponse(stderr="not found", returncode=1), "")
    await vault.generate("Agent/random-key/password", length=24)

    assert len(op_cli.calls) == 2
    first_cmd = list(op_cli.calls[0].args)
    assert first_cmd[2] == "edit"

    second_cmd = list(op_cli.calls[1].args)
    assert second_cmd[2] == "create"
    assert "--vault" in second_cmd
    assert "Agent" in second_cmd
    assert any("24" in str(a) for a in second_cmd)


async def test_generate_default_length(vault: OnePasswordVault, op_cli: OpCLI):
    op_cli("")
    await vault.generate("Agent/random-key/password")

    cmd = list(op_cli.calls[0].args)
    assert any("32" in str(a) for a in cmd)


async def test_generate_bad_path(vault: OnePasswordVault):
    with pytest.raises(ValueError, match="vault/item/field"):
        await vault.generate("no-slash")


async def test_generate_op_failure(vault: OnePasswordVault, op_cli: OpCLI):
    failure = OpResponse(stderr="error", returncode=1)
    op_cli(failure, failure)
    with pytest.raises(RuntimeError, match="error"):
        await vault.generate("Agent/secret/password")


# --- delete ---


async def test_delete(vault: OnePasswordVault, op_cli: OpCLI):
    op_cli("")
    await vault.delete("Agent/old-secret/password")

    cmd = list(op_cli.calls[0].args)
    assert "delete" in cmd
    assert "old-secret" in cmd
    assert "--vault" in cmd
    assert "Agent" in cmd


async def test_delete_bad_path(vault: OnePasswordVault):
    with pytest.raises(ValueError, match="vault/item/field"):
        await vault.delete("no-slash")


async def test_delete_op_failure(vault: OnePasswordVault, op_cli: OpCLI):
    op_cli(OpResponse(stderr="not found", returncode=1))
    with pytest.raises(RuntimeError, match="not found"):
        await vault.delete("Agent/missing/password")
