"""Docket dependencies for Docketeer task functions."""

from contextvars import ContextVar
from datetime import timedelta
from pathlib import Path
from typing import cast

from docket import Docket
from docket.dependencies import Dependency

from docketeer import environment
from docketeer.brain import Brain
from docketeer.chat import ChatClient
from docketeer.executor import CommandExecutor
from docketeer.vault import Vault

# ContextVars — set in main() before the worker starts

_brain_var: ContextVar[Brain] = ContextVar("docketeer_brain")
_client_var: ContextVar[ChatClient] = ContextVar("docketeer_client")
_executor_var: ContextVar[CommandExecutor] = ContextVar("docketeer_executor")
_vault_var: ContextVar[Vault] = ContextVar("docketeer_vault")
_docket_var: ContextVar[Docket] = ContextVar("docketeer_docket")


def set_brain(brain: Brain) -> None:
    _brain_var.set(brain)


def set_client(client: ChatClient) -> None:
    _client_var.set(client)


def set_executor(executor: CommandExecutor) -> None:
    _executor_var.set(executor)


def set_vault(vault: Vault) -> None:
    _vault_var.set(vault)


def set_docket(docket: Docket) -> None:
    _docket_var.set(docket)


# --- CurrentBrain / CurrentChatClient / CurrentExecutor / CurrentVault / CurrentDocket ---


class _CurrentBrain(Dependency):
    async def __aenter__(self) -> Brain:
        return _brain_var.get()


def CurrentBrain() -> Brain:
    return cast(Brain, _CurrentBrain())


class _CurrentChatClient(Dependency):
    async def __aenter__(self) -> ChatClient:
        return _client_var.get()


def CurrentChatClient() -> ChatClient:
    return cast(ChatClient, _CurrentChatClient())


class _CurrentExecutor(Dependency):
    async def __aenter__(self) -> CommandExecutor:
        return _executor_var.get()


def CurrentExecutor() -> CommandExecutor:
    return cast(CommandExecutor, _CurrentExecutor())


class _CurrentVault(Dependency):
    async def __aenter__(self) -> Vault:
        return _vault_var.get()


def CurrentVault() -> Vault:
    return cast(Vault, _CurrentVault())


class _CurrentDocket(Dependency):
    async def __aenter__(self) -> Docket:
        return _docket_var.get()


def CurrentDocket() -> Docket:
    return cast(Docket, _CurrentDocket())


# --- WorkspacePath ---


class _WorkspacePath(Dependency):
    async def __aenter__(self) -> Path:
        return environment.get_path("DATA_DIR", "~/.docketeer") / "memory"


def WorkspacePath() -> Path:
    return cast(Path, _WorkspacePath())


# --- Environment (typed variants) ---


class _EnvironmentStr(Dependency):
    def __init__(self, name: str, default: str | None = None) -> None:
        self.name = name
        self.default = default

    async def __aenter__(self) -> str:
        if self.default is None:
            return environment.get_str(self.name)
        return environment.get_str(self.name, self.default)


def EnvironmentStr(name: str, default: str | None = None) -> str:
    return cast(str, _EnvironmentStr(name, default))


class _EnvironmentInt(Dependency):
    def __init__(self, name: str, default: int) -> None:
        self.name = name
        self.default = default

    async def __aenter__(self) -> int:
        return environment.get_int(self.name, self.default)


def EnvironmentInt(name: str, default: int) -> int:
    return cast(int, _EnvironmentInt(name, default))


class _EnvironmentTimedelta(Dependency):
    def __init__(self, name: str, default: timedelta) -> None:
        self.name = name
        self.default = default

    async def __aenter__(self) -> timedelta:
        return environment.get_timedelta(self.name, self.default)


def EnvironmentTimedelta(name: str, default: timedelta) -> timedelta:
    return cast(timedelta, _EnvironmentTimedelta(name, default))
