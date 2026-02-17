"""Tests for the MemoryVault test helper and resolve_env."""

import pytest

from docketeer.testing import MemoryVault
from docketeer.vault import (
    SecretEnvRef,
    SecretReference,
    SecretResolutionError,
    resolve_env,
)


async def test_empty_vault_lists_nothing():
    vault = MemoryVault()
    assert await vault.list_secrets() == []


async def test_store_and_list():
    vault = MemoryVault()
    await vault.store("db/password", "secret123")
    refs = await vault.list_secrets()
    assert refs == [SecretReference(name="db/password")]


async def test_store_and_resolve():
    vault = MemoryVault()
    await vault.store("db/password", "secret123")
    assert await vault.resolve("db/password") == "secret123"


async def test_resolve_missing_raises():
    vault = MemoryVault()
    with pytest.raises(KeyError):
        await vault.resolve("nonexistent")


async def test_generate_creates_secret():
    vault = MemoryVault()
    await vault.generate("random-key", length=16)
    value = await vault.resolve("random-key")
    assert len(value) == 16


async def test_generate_default_length():
    vault = MemoryVault()
    await vault.generate("random-key")
    value = await vault.resolve("random-key")
    assert len(value) == 32


async def test_delete_removes_secret():
    vault = MemoryVault()
    await vault.store("temp", "val")
    await vault.delete("temp")
    assert await vault.list_secrets() == []


async def test_delete_missing_raises():
    vault = MemoryVault()
    with pytest.raises(KeyError):
        await vault.delete("nonexistent")


async def test_store_overwrites_existing():
    vault = MemoryVault()
    await vault.store("key", "old")
    await vault.store("key", "new")
    assert await vault.resolve("key") == "new"


async def test_preloaded_secrets():
    vault = MemoryVault({"api-key": "sk-123", "token": "tok-456"})
    refs = await vault.list_secrets()
    names = {r.name for r in refs}
    assert names == {"api-key", "token"}
    assert await vault.resolve("api-key") == "sk-123"


# --- resolve_env ---


async def test_resolve_env_plain_strings():
    vault = MemoryVault()
    result = await resolve_env({"TZ": "UTC", "HOME": "/tmp"}, vault)
    assert result == {"TZ": "UTC", "HOME": "/tmp"}


async def test_resolve_env_secret_refs():
    vault = MemoryVault({"api-key": "sk-123", "db/pass": "hunter2"})
    result = await resolve_env(
        {
            "API_KEY": SecretEnvRef(secret="api-key"),
            "DB_PASS": SecretEnvRef(secret="db/pass"),
        },
        vault,
    )
    assert result == {"API_KEY": "sk-123", "DB_PASS": "hunter2"}


async def test_resolve_env_mixed():
    vault = MemoryVault({"api-key": "sk-123"})
    result = await resolve_env(
        {"TZ": "UTC", "API_KEY": SecretEnvRef(secret="api-key")},
        vault,
    )
    assert result == {"TZ": "UTC", "API_KEY": "sk-123"}


async def test_resolve_env_missing_secret_raises():
    vault = MemoryVault()
    with pytest.raises(SecretResolutionError, match="nonexistent"):
        await resolve_env({"KEY": SecretEnvRef(secret="nonexistent")}, vault)


async def test_resolve_env_error_names_variable():
    vault = MemoryVault()
    with pytest.raises(SecretResolutionError, match=r"\$MY_VAR"):
        await resolve_env({"MY_VAR": SecretEnvRef(secret="missing")}, vault)


async def test_resolve_env_empty():
    vault = MemoryVault()
    result = await resolve_env({}, vault)
    assert result == {}
