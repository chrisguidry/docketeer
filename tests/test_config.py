"""Tests for configuration loading from environment variables."""

from pathlib import Path

import pytest

from docketeer.config import Config


@pytest.fixture()
def _env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKETEER_ROCKETCHAT_URL", "https://chat.example.com")
    monkeypatch.setenv("DOCKETEER_ROCKETCHAT_USERNAME", "bot")
    monkeypatch.setenv("DOCKETEER_ROCKETCHAT_PASSWORD", "secret")
    monkeypatch.setenv("DOCKETEER_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("DOCKETEER_BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("DOCKETEER_CLAUDE_MODEL", raising=False)
    monkeypatch.delenv("DOCKETEER_DOCKET_URL", raising=False)
    monkeypatch.delenv("DOCKETEER_DOCKET_NAME", raising=False)
    monkeypatch.delenv("DOCKETEER_DATA_DIR", raising=False)
    monkeypatch.delenv("DOCKETEER_REVERIE_MINUTES", raising=False)
    monkeypatch.delenv("DOCKETEER_CONSOLIDATION_CRON", raising=False)


@pytest.mark.usefixtures("_env_vars")
def test_from_env_required_vars():
    cfg = Config.from_env()
    assert cfg.rocketchat_url == "https://chat.example.com"
    assert cfg.rocketchat_username == "bot"
    assert cfg.rocketchat_password == "secret"
    assert cfg.anthropic_api_key == "sk-test"


def test_from_env_missing_var_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DOCKETEER_ROCKETCHAT_URL", raising=False)
    monkeypatch.delenv("DOCKETEER_ROCKETCHAT_USERNAME", raising=False)
    monkeypatch.delenv("DOCKETEER_ROCKETCHAT_PASSWORD", raising=False)
    monkeypatch.delenv("DOCKETEER_ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(KeyError):
        Config.from_env()


@pytest.mark.usefixtures("_env_vars")
def test_from_env_defaults():
    cfg = Config.from_env()
    assert cfg.brave_api_key == ""
    assert cfg.claude_model == "claude-opus-4-6"
    assert cfg.docket_url == "redis://localhost:6379/0"
    assert cfg.docket_name == "docketeer"
    assert cfg.reverie_minutes is None
    assert cfg.consolidation_cron is None


@pytest.mark.usefixtures("_env_vars")
def test_from_env_custom_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("DOCKETEER_DATA_DIR", str(tmp_path / "custom"))
    cfg = Config.from_env()
    assert cfg.data_dir == tmp_path / "custom"


@pytest.mark.usefixtures("_env_vars")
def test_from_env_cycle_overrides(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DOCKETEER_REVERIE_MINUTES", "30")
    monkeypatch.setenv("DOCKETEER_CONSOLIDATION_CRON", "0 8 * * *")
    cfg = Config.from_env()
    assert cfg.reverie_minutes == 30
    assert cfg.consolidation_cron == "0 8 * * *"


def test_workspace_path():
    cfg = Config(
        rocketchat_url="",
        rocketchat_username="",
        rocketchat_password="",
        anthropic_api_key="",
        data_dir=Path("/data"),
    )
    assert cfg.workspace_path == Path("/data/memory")


def test_audit_path():
    cfg = Config(
        rocketchat_url="",
        rocketchat_username="",
        rocketchat_password="",
        anthropic_api_key="",
        data_dir=Path("/data"),
    )
    assert cfg.audit_path == Path("/data/audit")
