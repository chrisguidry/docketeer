"""Tests for the Vault ABC, NullVault, and SecretReference."""

import pytest

from docketeer.plugins import PluginUnavailable
from docketeer.vault import NullVault, SecretReference, Vault


def test_secret_reference_has_name():
    ref = SecretReference(name="infra/db-password")
    assert ref.name == "infra/db-password"


def test_vault_is_abstract():
    with pytest.raises(TypeError):
        Vault()


def test_null_vault_is_falsy():
    assert not NullVault()


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("list_secrets", ()),
        ("resolve", ("key",)),
        ("store", ("key", "val")),
        ("generate", ("key",)),
        ("delete", ("key",)),
    ],
)
async def test_null_vault_raises(method: str, args: tuple[str, ...]):
    vault = NullVault()
    with pytest.raises(PluginUnavailable, match="vault"):
        await getattr(vault, method)(*args)
