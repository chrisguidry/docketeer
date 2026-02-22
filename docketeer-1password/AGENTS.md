# docketeer-1password

1Password vault plugin. Implements the `docketeer.vault` entry point so the
agent can store and resolve secrets through the 1Password CLI (`op`).

## Structure

- **`vault.py`** — the `OnePasswordVault` class. Shells out to the `op` CLI
  for all operations (list, store, resolve, generate, delete). Secrets are
  organized in a configurable 1Password vault.

## Testing

All `op` CLI calls are mocked via `subprocess` patches. Tests verify the
command construction and output parsing without needing 1Password installed.
