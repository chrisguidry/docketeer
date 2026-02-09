# docketeer-1password

1Password vault plugin for [Docketeer](https://github.com/chrisguidry/docketeer).

Provides secrets management backed by 1Password via the `op` CLI and service
account tokens. Secret names use `vault/item/field` paths (e.g.
`Agent/db-cred/password`).

## Installation

```bash
pip install docketeer-1password
```

## Configuration

Set `DOCKETEER_OP_SERVICE_ACCOUNT_TOKEN` in the environment to authenticate
with 1Password. The plugin translates this to `OP_SERVICE_ACCOUNT_TOKEN` when
running `op` commands. The service account grants access to one or more
1Password vaults.
