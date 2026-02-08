"""Tests for Docketeer's Docket dependencies."""

from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from docketeer.dependencies import (
    CurrentBrain,
    CurrentChatClient,
    CurrentExecutor,
    EnvironmentInt,
    EnvironmentStr,
    EnvironmentTimedelta,
    WorkspacePath,
    _brain_var,
    _client_var,
    _CurrentBrain,
    _CurrentChatClient,
    _CurrentExecutor,
    _EnvironmentInt,
    _EnvironmentStr,
    _EnvironmentTimedelta,
    _executor_var,
    _WorkspacePath,
    set_brain,
    set_client,
    set_executor,
)


async def test_current_brain():
    brain = AsyncMock()
    token = _brain_var.set(brain)
    try:
        dep = _CurrentBrain()
        assert await dep.__aenter__() is brain
    finally:
        _brain_var.reset(token)


async def test_current_brain_factory_returns_dependency():
    result = CurrentBrain()
    assert isinstance(result, _CurrentBrain)


async def test_current_chat_client():
    client = AsyncMock()
    token = _client_var.set(client)
    try:
        dep = _CurrentChatClient()
        assert await dep.__aenter__() is client
    finally:
        _client_var.reset(token)


async def test_current_chat_client_factory_returns_dependency():
    result = CurrentChatClient()
    assert isinstance(result, _CurrentChatClient)


def test_set_brain():
    brain = AsyncMock()
    set_brain(brain)
    assert _brain_var.get() is brain


def test_set_client():
    client = AsyncMock()
    set_client(client)
    assert _client_var.get() is client


async def test_workspace_path(tmp_path: Path):
    with patch.dict("os.environ", {"DOCKETEER_DATA_DIR": str(tmp_path)}):
        dep = _WorkspacePath()
        result = await dep.__aenter__()
    assert result == tmp_path / "memory"


async def test_workspace_path_factory_returns_dependency():
    result = WorkspacePath()
    assert isinstance(result, _WorkspacePath)


# --- EnvironmentStr ---


async def test_environment_str_default():
    dep = _EnvironmentStr("TEST_VAR", "fallback")
    with patch.dict("os.environ", {}, clear=False):
        result = await dep.__aenter__()
    assert result == "fallback"


async def test_environment_str_from_env():
    dep = _EnvironmentStr("TEST_VAR", "fallback")
    with patch.dict("os.environ", {"DOCKETEER_TEST_VAR": "from_env"}):
        result = await dep.__aenter__()
    assert result == "from_env"


async def test_environment_str_required():
    dep = _EnvironmentStr("REQUIRED_VAR")
    with patch.dict("os.environ", {"DOCKETEER_REQUIRED_VAR": "found"}):
        result = await dep.__aenter__()
    assert result == "found"


async def test_environment_str_required_missing():
    dep = _EnvironmentStr("MISSING_VAR")
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(KeyError):
            await dep.__aenter__()


def test_environment_str_factory():
    result = EnvironmentStr("X", "default")
    assert isinstance(result, _EnvironmentStr)


def test_environment_str_factory_no_default():
    result = EnvironmentStr("X")
    assert isinstance(result, _EnvironmentStr)


# --- EnvironmentInt ---


async def test_environment_int_default():
    dep = _EnvironmentInt("COUNT", 42)
    with patch.dict("os.environ", {}, clear=False):
        result = await dep.__aenter__()
    assert result == 42


async def test_environment_int_from_env():
    dep = _EnvironmentInt("COUNT", 42)
    with patch.dict("os.environ", {"DOCKETEER_COUNT": "99"}):
        result = await dep.__aenter__()
    assert result == 99


def test_environment_int_factory():
    result = EnvironmentInt("X", 10)
    assert isinstance(result, _EnvironmentInt)


# --- EnvironmentTimedelta ---


async def test_environment_timedelta_default():
    dep = _EnvironmentTimedelta("INTERVAL", timedelta(minutes=5))
    with patch.dict("os.environ", {}, clear=False):
        result = await dep.__aenter__()
    assert result == timedelta(minutes=5)


async def test_environment_timedelta_from_env():
    dep = _EnvironmentTimedelta("INTERVAL", timedelta(minutes=5))
    with patch.dict("os.environ", {"DOCKETEER_INTERVAL": "PT10M"}):
        result = await dep.__aenter__()
    assert result == timedelta(minutes=10)


def test_environment_timedelta_factory():
    result = EnvironmentTimedelta("X", timedelta(hours=1))
    assert isinstance(result, _EnvironmentTimedelta)


# --- CurrentExecutor ---


async def test_current_executor():
    executor = AsyncMock()
    token = _executor_var.set(executor)
    try:
        dep = _CurrentExecutor()
        assert await dep.__aenter__() is executor
    finally:
        _executor_var.reset(token)


async def test_current_executor_factory_returns_dependency():
    result = CurrentExecutor()
    assert isinstance(result, _CurrentExecutor)


def test_set_executor():
    executor = AsyncMock()
    set_executor(executor)
    assert _executor_var.get() is executor
