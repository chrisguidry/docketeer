"""Tests for the package entry point."""

import os
from unittest.mock import patch

from docketeer_1password import create_vault
from docketeer_1password.vault import OnePasswordVault


def test_create_vault_reads_docketeer_env_var():
    with patch.dict(os.environ, {"DOCKETEER_OP_SERVICE_ACCOUNT_TOKEN": "sa-tok-123"}):
        vault = create_vault()
    assert isinstance(vault, OnePasswordVault)
    assert vault._token == "sa-tok-123"
