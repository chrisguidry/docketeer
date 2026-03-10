"""Tests for MCP server configuration."""

from pathlib import Path

from docketeer.hooks import parse_frontmatter
from docketeer.vault import SecretEnvRef
from docketeer_mcp.config import (
    CachedToolInfo,
    MCPServerConfig,
    load_all_tool_catalogs,
    load_servers,
    load_tool_catalog,
    remove_server,
    remove_tool_catalog,
    save_server,
    save_tool_catalog,
)


def test_config_is_stdio():
    c = MCPServerConfig(name="t", command="uvx", args=["server"])
    assert c.is_stdio
    assert not c.is_http


def test_config_is_http():
    c = MCPServerConfig(name="t", url="https://example.com/mcp")
    assert c.is_http
    assert not c.is_stdio


def test_config_neither():
    c = MCPServerConfig(name="t")
    assert not c.is_stdio
    assert not c.is_http


def test_load_servers_no_dir(workspace: Path):
    assert load_servers(workspace) == {}


def test_load_servers_stdio(workspace: Path):
    mcp_dir = workspace / "mcp"
    mcp_dir.mkdir()
    (mcp_dir / "time.md").write_text(
        "---\ncommand: uvx\nargs: [mcp-server-time]\n"
        "env:\n  TZ: UTC\nnetwork_access: true\n---\n"
    )
    servers = load_servers(workspace)
    assert "time" in servers
    s = servers["time"]
    assert s.name == "time"
    assert s.command == "uvx"
    assert s.args == ["mcp-server-time"]
    assert s.env == {"TZ": "UTC"}
    assert s.network_access is True
    assert s.is_stdio


def test_load_servers_http(workspace: Path):
    mcp_dir = workspace / "mcp"
    mcp_dir.mkdir()
    (mcp_dir / "weather.md").write_text(
        "---\nurl: https://weather.example.com/mcp\n"
        "headers:\n  Authorization: Bearer tok\n---\n"
    )
    servers = load_servers(workspace)
    assert "weather" in servers
    s = servers["weather"]
    assert s.url == "https://weather.example.com/mcp"
    assert s.headers == {"Authorization": "Bearer tok"}
    assert s.is_http


def test_load_servers_skips_unreadable(workspace: Path):
    mcp_dir = workspace / "mcp"
    mcp_dir.mkdir()
    (mcp_dir / "good.md").write_text("---\ncommand: echo\n---\n")
    bad = mcp_dir / "bad.md"
    bad.write_text("---\ncommand: echo\n---\n")
    bad.chmod(0o000)
    servers = load_servers(workspace)
    assert "good" in servers
    assert "bad" not in servers
    bad.chmod(0o644)


def test_load_servers_skips_no_frontmatter(workspace: Path):
    mcp_dir = workspace / "mcp"
    mcp_dir.mkdir()
    (mcp_dir / "good.md").write_text("---\ncommand: echo\n---\n")
    (mcp_dir / "bad.md").write_text("Just plain text, no frontmatter.")
    servers = load_servers(workspace)
    assert "good" in servers
    assert "bad" not in servers


def test_load_servers_sorted(workspace: Path):
    mcp_dir = workspace / "mcp"
    mcp_dir.mkdir()
    (mcp_dir / "beta.md").write_text("---\ncommand: b\n---\n")
    (mcp_dir / "alpha.md").write_text("---\ncommand: a\n---\n")
    servers = load_servers(workspace)
    assert list(servers.keys()) == ["alpha", "beta"]


def test_save_server_stdio(workspace: Path):
    config = MCPServerConfig(
        name="time",
        command="uvx",
        args=["mcp-server-time"],
        env={"TZ": "UTC"},
        network_access=True,
    )
    save_server(workspace, config)
    content = (workspace / "mcp" / "time.md").read_text()
    meta, _ = parse_frontmatter(content)
    assert meta["command"] == "uvx"
    assert meta["args"] == ["mcp-server-time"]
    assert meta["env"] == {"TZ": "UTC"}
    assert meta["network_access"] is True


def test_save_server_stdio_minimal(workspace: Path):
    config = MCPServerConfig(name="simple", command="echo")
    save_server(workspace, config)
    content = (workspace / "mcp" / "simple.md").read_text()
    meta, _ = parse_frontmatter(content)
    assert meta == {"command": "echo"}


def test_save_server_http(workspace: Path):
    config = MCPServerConfig(
        name="api",
        url="https://api.example.com/mcp",
        headers={"X-Key": "secret"},
    )
    save_server(workspace, config)
    content = (workspace / "mcp" / "api.md").read_text()
    meta, _ = parse_frontmatter(content)
    assert meta["url"] == "https://api.example.com/mcp"
    assert meta["headers"] == {"X-Key": "secret"}


def test_save_server_http_minimal(workspace: Path):
    config = MCPServerConfig(name="bare", url="https://example.com/mcp")
    save_server(workspace, config)
    content = (workspace / "mcp" / "bare.md").read_text()
    meta, _ = parse_frontmatter(content)
    assert meta == {"url": "https://example.com/mcp"}


def test_save_server_creates_dir(workspace: Path):
    save_server(workspace, MCPServerConfig(name="test", command="echo"))
    assert (workspace / "mcp" / "test.md").is_file()


def test_save_server_empty_config(workspace: Path):
    config = MCPServerConfig(name="empty")
    save_server(workspace, config)
    content = (workspace / "mcp" / "empty.md").read_text()
    meta, _ = parse_frontmatter(content)
    assert meta == {}


def test_save_server_preserves_body(workspace: Path):
    mcp_dir = workspace / "mcp"
    mcp_dir.mkdir()
    (mcp_dir / "time.md").write_text("---\ncommand: uvx\n---\nServer notes here.")
    config = MCPServerConfig(name="time", command="npx")
    save_server(workspace, config)
    content = (mcp_dir / "time.md").read_text()
    meta, body = parse_frontmatter(content)
    assert meta["command"] == "npx"
    assert body == "Server notes here."


def test_remove_server_exists(workspace: Path):
    mcp_dir = workspace / "mcp"
    mcp_dir.mkdir()
    (mcp_dir / "doomed.md").write_text("---\ncommand: echo\n---\n")
    assert remove_server(workspace, "doomed") is True
    assert not (mcp_dir / "doomed.md").exists()


def test_remove_server_missing(workspace: Path):
    assert remove_server(workspace, "nonexistent") is False


# --- auth field ---


def test_config_auth_default():
    c = MCPServerConfig(name="t", url="https://example.com/mcp")
    assert c.auth == ""


def test_load_servers_with_auth(workspace: Path):
    mcp_dir = workspace / "mcp"
    mcp_dir.mkdir()
    (mcp_dir / "api.md").write_text(
        "---\nurl: https://api.example.com/mcp\nauth: mcp/api/token\n---\n"
    )
    servers = load_servers(workspace)
    assert servers["api"].auth == "mcp/api/token"


def test_load_servers_without_auth(workspace: Path):
    mcp_dir = workspace / "mcp"
    mcp_dir.mkdir()
    (mcp_dir / "api.md").write_text("---\nurl: https://api.example.com/mcp\n---\n")
    servers = load_servers(workspace)
    assert servers["api"].auth == ""


def test_save_server_http_with_auth(workspace: Path):
    config = MCPServerConfig(
        name="api",
        url="https://api.example.com/mcp",
        auth="mcp/api/token",
    )
    save_server(workspace, config)
    content = (workspace / "mcp" / "api.md").read_text()
    meta, _ = parse_frontmatter(content)
    assert meta["auth"] == "mcp/api/token"


def test_save_server_http_without_auth(workspace: Path):
    config = MCPServerConfig(name="api", url="https://api.example.com/mcp")
    save_server(workspace, config)
    content = (workspace / "mcp" / "api.md").read_text()
    meta, _ = parse_frontmatter(content)
    assert "auth" not in meta


# --- secret env refs ---


def test_load_servers_with_secret_env(workspace: Path):
    mcp_dir = workspace / "mcp"
    mcp_dir.mkdir()
    (mcp_dir / "gw.md").write_text(
        "---\n"
        "command: uvx\n"
        "args: [google-workspace-mcp]\n"
        "env:\n"
        "  TZ: UTC\n"
        "  CLIENT_ID:\n"
        "    secret: mcp/gw/client-id\n"
        "  CLIENT_SECRET:\n"
        "    secret: mcp/gw/client-secret\n"
        "---\n"
    )
    servers = load_servers(workspace)
    env = servers["gw"].env
    assert env["TZ"] == "UTC"
    assert env["CLIENT_ID"] == SecretEnvRef(secret="mcp/gw/client-id")
    assert env["CLIENT_SECRET"] == SecretEnvRef(secret="mcp/gw/client-secret")


def test_save_server_with_secret_env(workspace: Path):
    cfg = MCPServerConfig(
        name="gw",
        command="uvx",
        env={
            "TZ": "UTC",
            "CLIENT_ID": SecretEnvRef(secret="mcp/gw/client-id"),
        },
    )
    save_server(workspace, cfg)
    content = (workspace / "mcp" / "gw.md").read_text()
    meta, _ = parse_frontmatter(content)
    assert meta["env"]["TZ"] == "UTC"
    assert meta["env"]["CLIENT_ID"] == {"secret": "mcp/gw/client-id"}


def test_load_save_roundtrip_secret_env(workspace: Path):
    mcp_dir = workspace / "mcp"
    mcp_dir.mkdir()
    (mcp_dir / "rt.md").write_text(
        "---\n"
        "command: echo\n"
        "env:\n"
        "  PLAIN: value\n"
        "  SECRET:\n"
        "    secret: vault/path\n"
        "---\n"
    )
    servers = load_servers(workspace)
    save_server(workspace, servers["rt"])
    content = (mcp_dir / "rt.md").read_text()
    meta, _ = parse_frontmatter(content)
    assert meta["env"]["PLAIN"] == "value"
    assert meta["env"]["SECRET"] == {"secret": "vault/path"}


# --- tool catalog persistence ---


def test_save_and_load_tool_catalog(mcp_dir: Path):
    tools = [
        CachedToolInfo(name="get_time", description="Gets the time"),
        CachedToolInfo(name="set_alarm", description="Sets an alarm"),
    ]
    save_tool_catalog("time", tools)
    loaded = load_tool_catalog("time")
    assert len(loaded) == 2
    assert loaded[0].name == "get_time"
    assert loaded[0].description == "Gets the time"
    assert loaded[1].name == "set_alarm"


def test_load_tool_catalog_missing(mcp_dir: Path):
    assert load_tool_catalog("nonexistent") == []


def test_load_tool_catalog_bad_json(mcp_dir: Path):
    catalog_dir = mcp_dir / "catalogs"
    catalog_dir.mkdir()
    (catalog_dir / "bad.json").write_text("not json{{{")
    assert load_tool_catalog("bad") == []


def test_load_all_tool_catalogs(mcp_dir: Path):
    save_tool_catalog("time", [CachedToolInfo(name="get_time", description="time")])
    save_tool_catalog("weather", [CachedToolInfo(name="forecast", description="wx")])
    catalogs = load_all_tool_catalogs()
    assert "time" in catalogs
    assert "weather" in catalogs
    assert len(catalogs["time"]) == 1
    assert len(catalogs["weather"]) == 1


def test_load_all_tool_catalogs_no_dir(mcp_dir: Path):
    assert load_all_tool_catalogs() == {}


def test_remove_tool_catalog(mcp_dir: Path):
    save_tool_catalog("time", [CachedToolInfo(name="t", description="d")])
    assert remove_tool_catalog("time") is True
    assert load_tool_catalog("time") == []


def test_remove_tool_catalog_missing(mcp_dir: Path):
    assert remove_tool_catalog("nonexistent") is False


def test_load_all_tool_catalogs_skips_empty(mcp_dir: Path):
    save_tool_catalog("good", [CachedToolInfo(name="t", description="d")])
    catalog_dir = mcp_dir / "catalogs"
    (catalog_dir / "empty.json").write_text("[]")
    catalogs = load_all_tool_catalogs()
    assert "good" in catalogs
    assert "empty" not in catalogs
