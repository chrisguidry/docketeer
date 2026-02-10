"""Tests for MCP server configuration."""

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from docketeer_mcp.config import (
    MCPServerConfig,
    _validate_name,
    load_servers,
    remove_server,
    save_server,
)


@pytest.fixture()
def data_dir(tmp_path: Path) -> Generator[Path]:
    d = tmp_path / "data"
    d.mkdir()
    with patch("docketeer_mcp.config.environment") as mock_env:
        mock_env.DATA_DIR = d
        yield d


@pytest.fixture()
def mcp_dir(data_dir: Path) -> Path:
    d = data_dir / "mcp"
    d.mkdir()
    return d


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
