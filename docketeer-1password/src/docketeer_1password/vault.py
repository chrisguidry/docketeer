"""1Password vault implementation using the op CLI."""

import asyncio
import json
import os

from docketeer.vault import SecretReference, Vault


def _parse_name(name: str) -> tuple[str, str, str]:
    """Split a 'vault/item/field' path into (vault, item, field)."""
    parts = name.split("/", 2)
    if len(parts) != 3:
        raise ValueError(f"Secret name must be 'vault/item/field', got: {name!r}")
    return parts[0], parts[1], parts[2]


class OnePasswordVault(Vault):
    """Vault backed by 1Password via the op CLI.

    Auth uses DOCKETEER_OP_SERVICE_ACCOUNT_TOKEN, which gets translated to
    OP_SERVICE_ACCOUNT_TOKEN in the subprocess environment so the op CLI
    picks it up.
    """

    def __init__(self, token: str) -> None:
        self._token = token

    async def _run_op(self, *args: str) -> str:
        """Run an op CLI command and return stdout."""
        env = {**os.environ, "OP_SERVICE_ACCOUNT_TOKEN": self._token}
        proc = await asyncio.create_subprocess_exec(
            "op",
            *args,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"op {' '.join(args[:2])} failed: {stderr.decode(errors='replace').strip()}"
            )
        return stdout.decode(errors="replace").strip()

    async def list(self) -> list[SecretReference]:
        vaults_raw = await self._run_op("vault", "list", "--format", "json")
        vaults = json.loads(vaults_raw)
        if not vaults:
            return []

        refs: list[SecretReference] = []
        for v in vaults:
            vault_name = v["name"]
            items_raw = await self._run_op(
                "item", "list", "--vault", v["id"], "--format", "json"
            )
            items = json.loads(items_raw)
            for item in items:
                detail_raw = await self._run_op(
                    "item", "get", item["id"], "--vault", v["id"], "--format", "json"
                )
                detail = json.loads(detail_raw)
                for field in detail.get("fields", []):
                    refs.append(
                        SecretReference(
                            name=f"{vault_name}/{item['title']}/{field['label']}"
                        )
                    )
        return refs

    async def resolve(self, name: str) -> str:
        vault, item, field = _parse_name(name)
        return await self._run_op(
            "item",
            "get",
            item,
            "--vault",
            vault,
            "--fields",
            field,
            "--reveal",
        )

    async def store(self, name: str, value: str) -> None:
        vault, item, field = _parse_name(name)
        await self._run_op(
            "item",
            "create",
            "--category",
            "Password",
            "--vault",
            vault,
            "--title",
            item,
            f"{field}={value}",
        )

    async def generate(self, name: str, length: int = 32) -> None:
        vault, item, field = _parse_name(name)
        await self._run_op(
            "item",
            "create",
            "--category",
            "Password",
            "--vault",
            vault,
            "--title",
            item,
            f"--generate-password={length},letters,digits,symbols",
        )

    async def delete(self, name: str) -> None:
        vault, item, field = _parse_name(name)
        await self._run_op(
            "item",
            "delete",
            item,
            "--vault",
            vault,
        )
