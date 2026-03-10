"""MCP server configuration loading and saving."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from docketeer import environment
from docketeer.hooks import parse_frontmatter, render_frontmatter
from docketeer.vault import SecretEnvRef


def _mcp_dir() -> Path:
    return environment.DATA_DIR / "mcp"


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""

    name: str

    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str | SecretEnvRef] = field(default_factory=dict)

    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)

    network_access: bool = False
    auth: str = ""

    @property
    def is_stdio(self) -> bool:
        return bool(self.command)

    @property
    def is_http(self) -> bool:
        return bool(self.url)


def _parse_env(raw: dict) -> dict[str, str | SecretEnvRef]:
    """Parse an env dict from frontmatter, converting secret objects to SecretEnvRef."""
    env: dict[str, str | SecretEnvRef] = {}
    for key, value in raw.items():
        if isinstance(value, dict) and "secret" in value:
            env[key] = SecretEnvRef(secret=value["secret"])
        else:
            env[key] = str(value)
    return env


def _serialize_env(env: dict[str, str | SecretEnvRef]) -> dict[str, str | dict]:
    """Serialize an env dict for YAML, converting SecretEnvRef back to dicts."""
    out: dict[str, str | dict] = {}
    for key, value in env.items():
        if isinstance(value, SecretEnvRef):
            out[key] = {"secret": value.secret}
        else:
            out[key] = value
    return out


def load_servers(workspace: Path) -> dict[str, MCPServerConfig]:
    """Load all server configs from workspace mcp/ directory."""
    mcp_dir = workspace / "mcp"
    if not mcp_dir.is_dir():
        return {}

    servers: dict[str, MCPServerConfig] = {}
    for path in sorted(mcp_dir.glob("*.md")):
        name = path.stem
        try:
            content = path.read_text()
        except OSError:
            continue

        meta, _ = parse_frontmatter(content)
        if not meta:
            continue

        servers[name] = MCPServerConfig(
            name=name,
            command=meta.get("command", ""),
            args=meta.get("args", []),
            env=_parse_env(meta.get("env", {})),
            url=meta.get("url", ""),
            headers=meta.get("headers", {}),
            network_access=meta.get("network_access", False),
            auth=meta.get("auth", ""),
        )
    return servers


def save_server(workspace: Path, config: MCPServerConfig) -> None:
    """Write a server config to the workspace as a markdown file."""
    mcp_dir = workspace / "mcp"
    mcp_dir.mkdir(parents=True, exist_ok=True)

    meta: dict[str, object] = {}
    if config.command:
        meta["command"] = config.command
        if config.args:
            meta["args"] = config.args
        if config.env:
            meta["env"] = _serialize_env(config.env)
        if config.network_access:
            meta["network_access"] = True

    if config.url:
        meta["url"] = config.url
        if config.headers:
            meta["headers"] = config.headers

    if config.auth:
        meta["auth"] = config.auth

    # Preserve existing body text
    path = mcp_dir / f"{config.name}.md"
    body = ""
    if path.is_file():
        _, body = parse_frontmatter(path.read_text())

    path.write_text(render_frontmatter(meta, body))


def remove_server(workspace: Path, name: str) -> bool:
    """Delete a server config file. Returns True if the file existed."""
    path = workspace / "mcp" / f"{name}.md"
    if not path.is_file():
        return False
    path.unlink()
    return True


# --- Tool catalog persistence ---


@dataclass
class CachedToolInfo:
    """Serializable tool metadata for disk caching."""

    name: str
    description: str


def save_tool_catalog(server_name: str, tools: list[CachedToolInfo]) -> None:
    """Persist a server's tool catalog to disk."""
    catalog_dir = _mcp_dir() / "catalogs"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    data = [{"name": t.name, "description": t.description} for t in tools]
    (catalog_dir / f"{server_name}.json").write_text(json.dumps(data, indent=2) + "\n")


def load_tool_catalog(server_name: str) -> list[CachedToolInfo]:
    """Load a server's cached tool catalog from disk."""
    path = _mcp_dir() / "catalogs" / f"{server_name}.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    return [
        CachedToolInfo(name=t["name"], description=t.get("description", ""))
        for t in data
    ]


def load_all_tool_catalogs() -> dict[str, list[CachedToolInfo]]:
    """Load all cached tool catalogs from disk."""
    catalog_dir = _mcp_dir() / "catalogs"
    if not catalog_dir.is_dir():
        return {}
    catalogs: dict[str, list[CachedToolInfo]] = {}
    for path in sorted(catalog_dir.glob("*.json")):
        server_name = path.stem
        tools = load_tool_catalog(server_name)
        if tools:
            catalogs[server_name] = tools
    return catalogs


def remove_tool_catalog(server_name: str) -> bool:
    """Delete a server's cached tool catalog. Returns True if the file existed."""
    path = _mcp_dir() / "catalogs" / f"{server_name}.json"
    if not path.is_file():
        return False
    path.unlink()
    return True
