"""Tests for the MemoryVault test helper."""

import pytest

from docketeer.testing import MemoryVault
from docketeer.vault import SecretReference


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
