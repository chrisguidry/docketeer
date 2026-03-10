"""Tests for backstage-to-workspace migration."""

import json
from pathlib import Path

import yaml

from docketeer.migration import (
    _convert_mcp,
    _convert_tuning,
    migrate_backstage,
)

# --- tuning conversion ---


def test_convert_tuning_basic():
    data = {"name": "github", "band": "wicket", "topic": "events"}
    result = _convert_tuning(data)
    assert result.startswith("---\n")
    assert result.endswith("---\n")
    meta = yaml.safe_load(result.split("---")[1])
    assert meta == {"band": "wicket", "topic": "events"}


def test_convert_tuning_strips_name():
    data = {"name": "github", "band": "wicket", "topic": "events"}
    meta = yaml.safe_load(_convert_tuning(data).split("---")[1])
    assert "name" not in meta


def test_convert_tuning_with_filters():
    data = {
        "band": "wicket",
        "topic": "events",
        "filters": [{"path": "payload.action", "op": "eq", "value": "push"}],
    }
    meta = yaml.safe_load(_convert_tuning(data).split("---")[1])
    assert meta["filters"] == [{"field": "payload.action", "op": "eq", "value": "push"}]


def test_convert_tuning_with_secret():
    data = {"band": "wicket", "topic": "events", "secret": "vault/github-token"}
    meta = yaml.safe_load(_convert_tuning(data).split("---")[1])
    assert "secret" not in meta
    assert meta["secrets"] == {"token": "vault/github-token"}


def test_convert_tuning_with_secrets_dict():
    data = {
        "band": "imap",
        "topic": "INBOX",
        "secrets": {
            "host": "Nix/GMail IMAP/host",
            "port": "Nix/GMail IMAP/port",
            "username": "Nix/GMail IMAP/username",
            "password": "Nix/GMail IMAP/password",
        },
    }
    meta = yaml.safe_load(_convert_tuning(data).split("---")[1])
    assert meta["secrets"] == {
        "host": "Nix/GMail IMAP/host",
        "port": "Nix/GMail IMAP/port",
        "username": "Nix/GMail IMAP/username",
        "password": "Nix/GMail IMAP/password",
    }


def test_convert_tuning_with_secrets_string():
    data = {"band": "wicket", "topic": "events", "secrets": "vault/token"}
    meta = yaml.safe_load(_convert_tuning(data).split("---")[1])
    assert meta["secrets"] == {"token": "vault/token"}


def test_convert_tuning_with_line():
    data = {"band": "wicket", "topic": "events", "line": "opensource"}
    meta = yaml.safe_load(_convert_tuning(data).split("---")[1])
    assert meta["line"] == "opensource"


def test_convert_tuning_empty_line_omitted():
    data = {"band": "wicket", "topic": "events", "line": ""}
    meta = yaml.safe_load(_convert_tuning(data).split("---")[1])
    assert "line" not in meta


def test_convert_tuning_empty_filters_omitted():
    data = {"band": "wicket", "topic": "events", "filters": []}
    meta = yaml.safe_load(_convert_tuning(data).split("---")[1])
    assert "filters" not in meta


# --- MCP conversion ---


def test_convert_mcp_stdio():
    data = {
        "command": "uvx",
        "args": ["mcp-server-time"],
        "networkAccess": True,
    }
    meta = yaml.safe_load(_convert_mcp(data).split("---")[1])
    assert meta["command"] == "uvx"
    assert meta["args"] == ["mcp-server-time"]
    assert meta["network_access"] is True
    assert "networkAccess" not in meta


def test_convert_mcp_stdio_with_env():
    data = {
        "command": "uvx",
        "args": [],
        "env": {"TZ": "UTC", "KEY": {"secret": "vault/key"}},
    }
    meta = yaml.safe_load(_convert_mcp(data).split("---")[1])
    assert meta["env"]["TZ"] == "UTC"
    assert meta["env"]["KEY"] == {"secret": "vault/key"}


def test_convert_mcp_http():
    data = {
        "url": "https://api.example.com/mcp",
        "headers": {"Authorization": "Bearer token"},
        "auth": "vault/auth-token",
    }
    meta = yaml.safe_load(_convert_mcp(data).split("---")[1])
    assert meta["url"] == "https://api.example.com/mcp"
    assert meta["headers"] == {"Authorization": "Bearer token"}
    assert meta["auth"] == "vault/auth-token"


def test_convert_mcp_network_access_false_omitted():
    data = {"command": "uvx", "networkAccess": False}
    meta = yaml.safe_load(_convert_mcp(data).split("---")[1])
    assert "network_access" not in meta


def test_convert_mcp_empty_args_omitted():
    data = {"command": "uvx"}
    meta = yaml.safe_load(_convert_mcp(data).split("---")[1])
    assert "args" not in meta


def test_convert_mcp_empty_env_omitted():
    data = {"command": "uvx", "env": {}}
    meta = yaml.safe_load(_convert_mcp(data).split("---")[1])
    assert "env" not in meta


def test_convert_mcp_empty_headers_omitted():
    data = {"url": "https://example.com/mcp", "headers": {}}
    meta = yaml.safe_load(_convert_mcp(data).split("---")[1])
    assert "headers" not in meta


# --- end-to-end migration ---


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_migrate_tuning(tmp_path: Path):
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _write_json(
        data_dir / "tunings" / "github.json",
        {"band": "wicket", "topic": "events"},
    )
    migrate_backstage(data_dir, workspace)

    md = workspace / "tunings" / "github.md"
    assert md.exists()
    assert not (data_dir / "tunings" / "github.json").exists()
    meta = yaml.safe_load(md.read_text().split("---")[1])
    assert meta["band"] == "wicket"


def test_migrate_mcp(tmp_path: Path):
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _write_json(
        data_dir / "mcp" / "time-server.json",
        {"command": "uvx", "args": ["mcp-server-time"]},
    )
    migrate_backstage(data_dir, workspace)

    md = workspace / "mcp" / "time-server.md"
    assert md.exists()
    assert not (data_dir / "mcp" / "time-server.json").exists()
    meta = yaml.safe_load(md.read_text().split("---")[1])
    assert meta["command"] == "uvx"


def test_skip_existing_workspace_file(tmp_path: Path):
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"

    _write_json(
        data_dir / "tunings" / "existing.json",
        {"band": "wicket", "topic": "events"},
    )
    target = workspace / "tunings" / "existing.md"
    target.parent.mkdir(parents=True)
    target.write_text("already here")

    migrate_backstage(data_dir, workspace)

    assert target.read_text() == "already here"
    # JSON should still be there since we didn't migrate
    assert (data_dir / "tunings" / "existing.json").exists()


def test_skip_unparseable_json(tmp_path: Path):
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    bad = data_dir / "tunings" / "broken.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("not json {{{")

    migrate_backstage(data_dir, workspace)

    assert not (workspace / "tunings" / "broken.md").exists()
    assert bad.exists()  # left in place


def test_no_source_dirs(tmp_path: Path):
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    migrate_backstage(data_dir, workspace)
    # No errors, no files created


def test_migrate_both_dirs(tmp_path: Path):
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _write_json(
        data_dir / "tunings" / "gh.json",
        {"band": "wicket", "topic": "events"},
    )
    _write_json(
        data_dir / "mcp" / "time.json",
        {"command": "uvx"},
    )

    migrate_backstage(data_dir, workspace)

    assert (workspace / "tunings" / "gh.md").exists()
    assert (workspace / "mcp" / "time.md").exists()
    assert not (data_dir / "tunings" / "gh.json").exists()
    assert not (data_dir / "mcp" / "time.json").exists()


def test_skips_non_json_files(tmp_path: Path):
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Put a non-JSON file in the tunings dir
    tunings_dir = data_dir / "tunings"
    tunings_dir.mkdir(parents=True)
    (tunings_dir / "notes.txt").write_text("not a config")

    migrate_backstage(data_dir, workspace)

    assert not (workspace / "tunings" / "notes.md").exists()
    assert (tunings_dir / "notes.txt").exists()


def test_migrate_tuning_data_dir(tmp_path: Path):
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Config file
    _write_json(
        data_dir / "tunings" / "gmail.json",
        {"band": "imap", "topic": "INBOX"},
    )
    # Data directory with cursor and signal log
    tuning_data = data_dir / "tunings" / "gmail"
    tuning_data.mkdir(parents=True)
    (tuning_data / "cursor").write_text("12345\n")
    (tuning_data / "2026-03-10.jsonl").write_text('{"signal_id": "12345"}\n')

    migrate_backstage(data_dir, workspace)

    # Config migrated
    assert (workspace / "tunings" / "gmail.md").exists()
    # Data dir moved
    assert (workspace / "tunings" / "gmail" / "cursor").exists()
    assert (workspace / "tunings" / "gmail" / "cursor").read_text() == "12345\n"
    assert (workspace / "tunings" / "gmail" / "2026-03-10.jsonl").exists()
    # Source removed
    assert not tuning_data.exists()


def test_migrate_data_dir_skips_existing(tmp_path: Path):
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"

    source = data_dir / "tunings" / "gmail"
    source.mkdir(parents=True)
    (source / "cursor").write_text("old\n")

    dest = workspace / "tunings" / "gmail"
    dest.mkdir(parents=True)
    (dest / "cursor").write_text("keep\n")

    migrate_backstage(data_dir, workspace)

    assert (dest / "cursor").read_text() == "keep\n"
    assert source.exists()


def test_skips_catalog_subdirectory(tmp_path: Path):
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # catalogs/ is a subdirectory of mcp/, should not be migrated
    catalogs = data_dir / "mcp" / "catalogs"
    catalogs.mkdir(parents=True)
    (catalogs / "server.json").write_text('{"name": "get_time"}')

    migrate_backstage(data_dir, workspace)

    assert not (workspace / "mcp" / "catalogs.md").exists()
