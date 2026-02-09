"""Tests for the Vault ABC and SecretReference."""

from docketeer.vault import SecretReference, Vault


def test_secret_reference_has_name():
    ref = SecretReference(name="infra/db-password")
    assert ref.name == "infra/db-password"


def test_vault_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        Vault()
