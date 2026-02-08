"""Tests for the ExecutorTransport."""

import json
import logging
from pathlib import Path

import anyio
import pytest
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage

from docketeer.executor import CommandExecutor, Mount, RunningProcess
from docketeer_mcp.transport import (
    ExecutorTransport,
    _stderr_logger,
    _stdin_writer,
    _stdout_reader,
)


class FakeStdin:
    """Minimal async writer that collects written bytes."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def write(self, data: bytes) -> None:
        self._buf.extend(data)

    async def drain(self) -> None:
        pass

    @property
    def written(self) -> bytes:
        return bytes(self._buf)


class FakeStdout:
    """Minimal async reader backed by a pre-loaded buffer."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    async def read(self, n: int) -> bytes:
        chunk = self._data[self._pos : self._pos + n]
        self._pos += n
        return chunk


class FakeProcess:
    """A minimal stand-in for RunningProcess that avoids real asyncio streams."""

    def __init__(self, stdout_data: bytes = b"", stderr_data: bytes = b"") -> None:
        self.stdin = FakeStdin()
        self.stdout = FakeStdout(stdout_data)
        self.stderr = FakeStdout(stderr_data) if stderr_data else None
        self.returncode: int | None = None
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15


class FakeExecutor(CommandExecutor):
    """A fake executor that returns a FakeProcess."""

    def __init__(self, stdout_data: bytes = b"") -> None:
        self._stdout_data = stdout_data
        self.last_process: FakeProcess | None = None
        self.last_command: list[str] = []
        self.last_env: dict[str, str] | None = None
        self.last_mounts: list[Mount] | None = None
        self.last_network_access: bool = False

    async def start(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        mounts: list[Mount] | None = None,
        network_access: bool = False,
        username: str | None = None,
    ) -> RunningProcess:
        self.last_command = command
        self.last_env = env
        self.last_mounts = mounts
        self.last_network_access = network_access
        self.last_process = FakeProcess(self._stdout_data)
        return self.last_process  # type: ignore[return-value]


async def test_stdout_reader_parses_jsonrpc():
    msg = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    process = FakeProcess(json.dumps(msg).encode() + b"\n")

    send, recv = anyio.create_memory_object_stream[SessionMessage | Exception](10)
    await _stdout_reader(process, send)  # type: ignore[arg-type]

    async with recv:
        item = recv.receive_nowait()
        assert isinstance(item, SessionMessage)
        assert item.message.root.id == 1  # type: ignore[union-attr]


async def test_stdout_reader_sends_parse_errors():
    process = FakeProcess(b"not valid json\n")

    send, recv = anyio.create_memory_object_stream[SessionMessage | Exception](10)
    await _stdout_reader(process, send)  # type: ignore[arg-type]

    async with recv:
        item = recv.receive_nowait()
        assert isinstance(item, Exception)


async def test_stdout_reader_skips_blank_lines():
    msg = {"jsonrpc": "2.0", "id": 1, "result": {}}
    process = FakeProcess(b"\n\n" + json.dumps(msg).encode() + b"\n\n")

    send, recv = anyio.create_memory_object_stream[SessionMessage | Exception](10)
    await _stdout_reader(process, send)  # type: ignore[arg-type]

    async with recv:
        item = recv.receive_nowait()
        assert isinstance(item, SessionMessage)


async def test_stdin_writer_serializes_messages():
    process = FakeProcess()
    msg = JSONRPCMessage.model_validate({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    session_msg = SessionMessage(msg)

    send, recv = anyio.create_memory_object_stream[SessionMessage](10)
    async with send:
        await send.send(session_msg)

    await _stdin_writer(process, recv)  # type: ignore[arg-type]

    parsed = json.loads(process.stdin.written.strip())
    assert parsed["jsonrpc"] == "2.0"
    assert parsed["method"] == "ping"


async def test_executor_transport_stores_params():
    executor = FakeExecutor()
    mounts = [Mount(source=Path("/src"), target=Path("/dst"))]
    transport = ExecutorTransport(
        executor=executor,
        command=["uvx", "mcp-server-test"],
        env={"KEY": "val"},
        mounts=mounts,
        network_access=True,
    )

    assert transport._executor is executor
    assert transport._command == ["uvx", "mcp-server-test"]
    assert transport._env == {"KEY": "val"}
    assert transport._mounts == mounts
    assert transport._network_access is True


async def test_executor_transport_connect_session():
    executor = FakeExecutor()
    transport = ExecutorTransport(executor=executor, command=["echo"])

    with pytest.raises(ExceptionGroup):
        async with transport.connect_session():
            raise RuntimeError("bail")

    assert executor.last_command == ["echo"]
    assert executor.last_env is None
    assert executor.last_mounts is None
    assert executor.last_network_access is False
    assert executor.last_process is not None
    assert executor.last_process.terminated


async def test_executor_transport_passes_through_env():
    executor = FakeExecutor()
    transport = ExecutorTransport(
        executor=executor, command=["echo"], env={"HOME": "/custom", "FOO": "bar"}
    )

    with pytest.raises(ExceptionGroup):
        async with transport.connect_session():
            raise RuntimeError("bail")

    assert executor.last_env == {"HOME": "/custom", "FOO": "bar"}


async def test_stderr_logger_logs_output(caplog: pytest.LogCaptureFixture):
    process = FakeProcess(stderr_data=b"Starting server...\nReady\n")

    with caplog.at_level(logging.INFO):
        await _stderr_logger(process, "test-server")  # type: ignore[arg-type]

    assert "[test-server] Starting server..." in caplog.text
    assert "[test-server] Ready" in caplog.text


async def test_stderr_logger_skips_blank_lines(caplog: pytest.LogCaptureFixture):
    process = FakeProcess(stderr_data=b"\n  \nOutput\n\n")

    with caplog.at_level(logging.INFO):
        await _stderr_logger(process, "srv")  # type: ignore[arg-type]

    assert "[srv] Output" in caplog.text
    assert caplog.text.count("[srv]") == 1


async def test_stderr_logger_handles_none_stderr():
    process = FakeProcess()  # stderr is None
    await _stderr_logger(process, "srv")  # type: ignore[arg-type]
