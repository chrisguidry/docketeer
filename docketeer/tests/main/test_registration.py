"""Tests for lock acquisition, chat/executor/vault discovery, and task plugin registration."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from docketeer.chat import discover_chat_backend
from docketeer.executor import discover_executor
from docketeer.main import (
    _instance_lock,
    _load_task_collections,
    _register_task_plugins,
    _task_collection_args,
)
from docketeer.testing import MemoryChat
from docketeer.tools import ToolContext
from docketeer.vault import discover_vault


def test_instance_lock_success(tmp_path: Path):
    with _instance_lock(tmp_path):
        assert (tmp_path / "docketeer.lock").exists()


def test_instance_lock_already_held(tmp_path: Path):
    import fcntl

    lock_path = tmp_path / "docketeer.lock"
    held = lock_path.open("w")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(SystemExit):
            with _instance_lock(tmp_path):
                ...  # pragma: no cover - never reached, SystemExit raised
    finally:
        held.close()


def test_discover_chat_backend():
    client = MemoryChat()
    module = MagicMock()
    module.create_client.return_value = client

    ep = MagicMock()
    ep.load.return_value = module
    with patch("docketeer.chat.discover_one", return_value=ep):
        result_client, register_fn = discover_chat_backend()
    assert result_client is client
    assert register_fn is not None


def test_discover_chat_backend_no_register_tools():
    client = MemoryChat()
    module = SimpleNamespace(create_client=lambda: client)

    ep = MagicMock()
    ep.load.return_value = module
    with patch("docketeer.chat.discover_one", return_value=ep):
        result_client, register_fn = discover_chat_backend()
    assert result_client is client
    # Should get the noop default, not None
    assert callable(register_fn)
    register_fn(client, ToolContext(workspace=Path("/tmp")))  # should not raise


def test_discover_chat_backend_no_plugins():
    with patch("docketeer.chat.discover_one", return_value=None):
        with pytest.raises(RuntimeError, match="No chat backend installed"):
            discover_chat_backend()


def test_discover_executor_present():
    module = MagicMock()
    executor = MagicMock()
    module.create_executor.return_value = executor

    ep = MagicMock()
    ep.load.return_value = module
    with patch("docketeer.executor.discover_one", return_value=ep):
        result = discover_executor()
    assert result is executor


def test_discover_executor_absent():
    from docketeer.executor import NullExecutor

    with patch("docketeer.executor.discover_one", return_value=None):
        result = discover_executor()
    assert isinstance(result, NullExecutor)


def test_discover_vault_present():
    module = MagicMock()
    vault = MagicMock()
    module.create_vault.return_value = vault

    ep = MagicMock()
    ep.load.return_value = module
    with patch("docketeer.vault.discover_explicit", return_value=ep):
        result = discover_vault()
    assert result is vault


def test_discover_vault_absent():
    from docketeer.vault import NullVault

    with patch("docketeer.vault.discover_explicit", return_value=None):
        result = discover_vault()
    assert isinstance(result, NullVault)


def test_load_task_collections_single_plugin():
    with patch(
        "docketeer.main.discover_all", return_value=[["docketeer_git:git_tasks"]]
    ):
        assert _load_task_collections() == ["docketeer_git:git_tasks"]


def test_load_task_collections_multiple_from_one_plugin():
    with patch(
        "docketeer.main.discover_all", return_value=[["pkg:tasks_a", "pkg:tasks_b"]]
    ):
        assert _load_task_collections() == ["pkg:tasks_a", "pkg:tasks_b"]


def test_load_task_collections_no_plugins():
    with patch("docketeer.main.discover_all", return_value=[]):
        assert _load_task_collections() == []


def test_register_task_plugins_registers_collections(mock_docket: MagicMock):
    with patch(
        "docketeer.main.discover_all", return_value=[["docketeer_git:git_tasks"]]
    ):
        _register_task_plugins(mock_docket)
    mock_docket.register_collection.assert_called_once_with("docketeer_git:git_tasks")


def test_register_task_plugins_no_plugins(mock_docket: MagicMock):
    with patch("docketeer.main.discover_all", return_value=[]):
        _register_task_plugins(mock_docket)
    mock_docket.register_collection.assert_not_called()


def test_task_collection_args_core_only():
    with patch("docketeer.main.discover_all", return_value=[]):
        args = _task_collection_args()
    assert args == ["--tasks", "docketeer.tasks:docketeer_tasks"]


def test_task_collection_args_with_plugins():
    with patch(
        "docketeer.main.discover_all", return_value=[["docketeer_git:git_tasks"]]
    ):
        args = _task_collection_args()
    assert args == [
        "--tasks",
        "docketeer.tasks:docketeer_tasks",
        "--tasks",
        "docketeer_git:git_tasks",
    ]
