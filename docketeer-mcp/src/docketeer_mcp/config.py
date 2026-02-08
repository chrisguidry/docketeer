"""MCP server configuration loading and saving."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from docketeer import environment

_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]*$")


def _mcp_dir() -> Path:
    return environment.DATA_DIR / "mcp"


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""

    name: str

    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)

    network_access: bool = False

    @property
    def is_stdio(self) -> bool:
        return bool(self.command)

    @property
    def is_http(self) -> bool:
        return bool(self.url)


def _validate_name(name: str) -> None:
    if not _NAME_PATTERN.match(name):
        raise ValueError(
            f"Invalid server name {name!r}: must start with a letter or underscore "
            f"and contain only letters, digits, underscores, and hyphens"
        )


def load_servers() -> dict[str, MCPServerConfig]:
    """Load all server configs from the data directory."""
    mcp_dir = _mcp_dir()
    if not mcp_dir.is_dir():
        return {}

    servers: dict[str, MCPServerConfig] = {}
    for path in sorted(mcp_dir.glob("*.json")):
        name = path.stem
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        servers[name] = MCPServerConfig(
            name=name,
            command=data.get("command", ""),
            args=data.get("args", []),
            env=data.get("env", {}),
            url=data.get("url", ""),
            headers=data.get("headers", {}),
            network_access=data.get("networkAccess", False),
        )
    return servers


def save_server(config: MCPServerConfig) -> None:
    """Write a server config to disk."""
    _validate_name(config.name)

    mcp_dir = _mcp_dir()
    mcp_dir.mkdir(parents=True, exist_ok=True)

    data: dict[str, object] = {}
    if config.command:
        data["command"] = config.command
        if config.args:
            data["args"] = config.args
        if config.env:
            data["env"] = config.env
        data["networkAccess"] = config.network_access
    elif config.url:
        data["url"] = config.url
        if config.headers:
            data["headers"] = config.headers

    path = mcp_dir / f"{config.name}.json"
    path.write_text(json.dumps(data, indent=2) + "\n")


def remove_server(name: str) -> bool:
    """Delete a server config file. Returns True if the file existed."""
    path = _mcp_dir() / f"{name}.json"
    if not path.is_file():
        return False
    path.unlink()
    return True
