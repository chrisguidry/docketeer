from docketeer import environment
from docketeer_1password.vault import OnePasswordVault


def create_vault() -> OnePasswordVault:
    token = environment.get_str("OP_SERVICE_ACCOUNT_TOKEN")
    return OnePasswordVault(token=token)


__all__ = ["OnePasswordVault", "create_vault"]
