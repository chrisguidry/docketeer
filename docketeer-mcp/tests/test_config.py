"""Tests for MCP server configuration."""

import json
from pathlib import Path

import pytest

from docketeer.vault import SecretEnvRef
from docketeer_mcp.config import (
    CachedToolInfo,
    MCPServerConfig,
    _validate_name,
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


def test_validate_name_valid():
    for name in ["time", "my_server", "a-b-c", "_private", "A1"]:
        _validate_name(name)


def test_validate_name_invalid():
    for name in ["", "123", "has space", "no!bang", "a/b"]:
        with pytest.raises(ValueError, match="Invalid server name"):
            _validate_name(name)


def test_load_servers_no_dir(data_dir: Path):
    assert load_servers() == {}


def test_load_servers_stdio(mcp_dir: Path):
    (mcp_dir / "time.json").write_text(
        json.dumps(
            {
                "command": "uvx",
                "args": ["mcp-server-time"],
                "env": {"TZ": "UTC"},
                "networkAccess": True,
            }
        )
    )
    servers = load_servers()
    assert "time" in servers
    s = servers["time"]
    assert s.name == "time"
    assert s.command == "uvx"
    assert s.args == ["mcp-server-time"]
    assert s.env == {"TZ": "UTC"}
    assert s.network_access is True
    assert s.is_stdio


def test_load_servers_http(mcp_dir: Path):
    (mcp_dir / "weather.json").write_text(
        json.dumps(
            {
                "url": "https://weather.example.com/mcp",
                "headers": {"Authorization": "Bearer tok"},
            }
        )
    )
    servers = load_servers()
    assert "weather" in servers
    s = servers["weather"]
    assert s.url == "https://weather.example.com/mcp"
    assert s.headers == {"Authorization": "Bearer tok"}
    assert s.is_http


def test_load_servers_skips_bad_json(mcp_dir: Path):
    (mcp_dir / "good.json").write_text('{"command": "echo"}')
    (mcp_dir / "bad.json").write_text("not json{{{")
    servers = load_servers()
    assert "good" in servers
    assert "bad" not in servers


def test_load_servers_sorted(mcp_dir: Path):
    (mcp_dir / "beta.json").write_text('{"command": "b"}')
    (mcp_dir / "alpha.json").write_text('{"command": "a"}')
    servers = load_servers()
    assert list(servers.keys()) == ["alpha", "beta"]


def test_save_server_stdio(mcp_dir: Path):
    config = MCPServerConfig(
        name="time",
        command="uvx",
        args=["mcp-server-time"],
        env={"TZ": "UTC"},
        network_access=True,
    )
    save_server(config)
    data = json.loads((mcp_dir / "time.json").read_text())
    assert data["command"] == "uvx"
    assert data["args"] == ["mcp-server-time"]
    assert data["env"] == {"TZ": "UTC"}
    assert data["networkAccess"] is True


def test_save_server_stdio_minimal(mcp_dir: Path):
    config = MCPServerConfig(name="simple", command="echo")
    save_server(config)
    data = json.loads((mcp_dir / "simple.json").read_text())
    assert data == {"command": "echo", "networkAccess": False}


def test_save_server_http(mcp_dir: Path):
    config = MCPServerConfig(
        name="api",
        url="https://api.example.com/mcp",
        headers={"X-Key": "secret"},
    )
    save_server(config)
    data = json.loads((mcp_dir / "api.json").read_text())
    assert data["url"] == "https://api.example.com/mcp"
    assert data["headers"] == {"X-Key": "secret"}


def test_save_server_http_minimal(mcp_dir: Path):
    config = MCPServerConfig(name="bare", url="https://example.com/mcp")
    save_server(config)
    data = json.loads((mcp_dir / "bare.json").read_text())
    assert data == {"url": "https://example.com/mcp"}


def test_save_server_creates_dir(data_dir: Path):
    save_server(MCPServerConfig(name="test", command="echo"))
    assert (data_dir / "mcp" / "test.json").is_file()


def test_save_server_empty_config(mcp_dir: Path):
    config = MCPServerConfig(name="empty")
    save_server(config)
    data = json.loads((mcp_dir / "empty.json").read_text())
    assert data == {}


def test_save_server_invalid_name(data_dir: Path):
    with pytest.raises(ValueError, match="Invalid server name"):
        save_server(MCPServerConfig(name="bad name!", command="echo"))


def test_remove_server_exists(mcp_dir: Path):
    (mcp_dir / "doomed.json").write_text("{}")
    assert remove_server("doomed") is True
    assert not (mcp_dir / "doomed.json").exists()


def test_remove_server_missing(mcp_dir: Path):
    assert remove_server("nonexistent") is False


# --- auth field ---


def test_config_auth_default():
    c = MCPServerConfig(name="t", url="https://example.com/mcp")
    assert c.auth == ""


def test_load_servers_with_auth(mcp_dir: Path):
    (mcp_dir / "api.json").write_text(
        json.dumps(
            {
                "url": "https://api.example.com/mcp",
                "auth": "mcp/api/token",
            }
        )
    )
    servers = load_servers()
    assert servers["api"].auth == "mcp/api/token"


def test_load_servers_without_auth(mcp_dir: Path):
    (mcp_dir / "api.json").write_text(
        json.dumps({"url": "https://api.example.com/mcp"})
    )
    servers = load_servers()
    assert servers["api"].auth == ""


def test_save_server_http_with_auth(mcp_dir: Path):
    config = MCPServerConfig(
        name="api",
        url="https://api.example.com/mcp",
        auth="mcp/api/token",
    )
    save_server(config)
    data = json.loads((mcp_dir / "api.json").read_text())
    assert data["auth"] == "mcp/api/token"


def test_save_server_http_without_auth(mcp_dir: Path):
    config = MCPServerConfig(name="api", url="https://api.example.com/mcp")
    save_server(config)
    data = json.loads((mcp_dir / "api.json").read_text())
    assert "auth" not in data


# --- secret env refs ---


def test_load_servers_with_secret_env(mcp_dir: Path):
    (mcp_dir / "gw.json").write_text(
        json.dumps(
            {
                "command": "uvx",
                "args": ["google-workspace-mcp"],
                "env": {
                    "TZ": "UTC",
                    "CLIENT_ID": {"secret": "mcp/gw/client-id"},
                    "CLIENT_SECRET": {"secret": "mcp/gw/client-secret"},
                },
            }
        )
    )
    servers = load_servers()
    env = servers["gw"].env
    assert env["TZ"] == "UTC"
    assert env["CLIENT_ID"] == SecretEnvRef(secret="mcp/gw/client-id")
    assert env["CLIENT_SECRET"] == SecretEnvRef(secret="mcp/gw/client-secret")


def test_save_server_with_secret_env(mcp_dir: Path):
    cfg = MCPServerConfig(
        name="gw",
        command="uvx",
        env={
            "TZ": "UTC",
            "CLIENT_ID": SecretEnvRef(secret="mcp/gw/client-id"),
        },
    )
    save_server(cfg)
    data = json.loads((mcp_dir / "gw.json").read_text())
    assert data["env"]["TZ"] == "UTC"
    assert data["env"]["CLIENT_ID"] == {"secret": "mcp/gw/client-id"}


def test_load_save_roundtrip_secret_env(mcp_dir: Path):
    original_env = {
        "PLAIN": "value",
        "SECRET": {"secret": "vault/path"},
    }
    (mcp_dir / "rt.json").write_text(
        json.dumps({"command": "echo", "env": original_env})
    )
    servers = load_servers()
    save_server(servers["rt"])
    data = json.loads((mcp_dir / "rt.json").read_text())
    assert data["env"] == original_env


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
