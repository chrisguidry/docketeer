"""Tests for the MCP bridge relay function."""

import io
import socket
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docketeer_bubblewrap.mcp_bridge import main, relay


def test_relay_forwards_stdin_to_socket(tmp_path: Path):
    """Data written to stdin arrives on the socket server."""
    socket_path = tmp_path / "test.sock"

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)

    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(socket_path))

    conn, _ = server.accept()

    stdin = io.BytesIO(b'{"method":"ping"}\n')
    stdout = io.BytesIO()

    # Close the connection after receiving data so relay returns
    def accept_and_close() -> None:
        data = conn.recv(4096)
        received.append(data)
        conn.close()

    received: list[bytes] = []
    t = threading.Thread(target=accept_and_close)
    t.start()

    relay(client, stdin, stdout)

    t.join(timeout=5)
    server.close()

    assert received[0] == b'{"method":"ping"}\n'


def test_relay_forwards_socket_to_stdout(tmp_path: Path):
    """Data sent by the socket server arrives on stdout."""
    socket_path = tmp_path / "test.sock"

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)

    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(socket_path))

    conn, _ = server.accept()

    stdin = io.BytesIO(b"")  # EOF immediately
    stdout = io.BytesIO()

    conn.sendall(b'{"result":"ok"}\n')
    conn.close()

    relay(client, stdin, stdout)
    server.close()

    assert stdout.getvalue() == b'{"result":"ok"}\n'


def test_relay_exits_when_socket_closes(tmp_path: Path):
    """relay() returns when the server closes the connection."""
    socket_path = tmp_path / "test.sock"

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)

    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(socket_path))

    conn, _ = server.accept()
    conn.close()

    stdin = io.BytesIO(b"")
    stdout = io.BytesIO()

    relay(client, stdin, stdout)
    server.close()

    assert stdout.getvalue() == b""


def test_relay_handles_broken_pipe_on_send(tmp_path: Path):
    """stdin_to_socket catches BrokenPipeError when the socket is closed."""
    socket_path = tmp_path / "test.sock"

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)

    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(socket_path))

    conn, _ = server.accept()

    # Close server side before stdin sends — triggers OSError on sendall
    conn.close()

    # Provide data that stdin_to_socket will try to send after the socket closes
    stdin = io.BytesIO(b'{"method":"ping"}\n')
    stdout = io.BytesIO()

    relay(client, stdin, stdout)
    server.close()


def test_relay_handles_recv_error():
    """Main recv loop catches OSError when the socket errors mid-stream."""
    mock_sock = MagicMock(spec=socket.socket)
    mock_sock.recv.side_effect = OSError("connection reset")

    stdin = io.BytesIO(b"")
    stdout = io.BytesIO()

    relay(mock_sock, stdin, stdout)
    mock_sock.close.assert_called_once()


def test_relay_handles_shutdown_error_after_stdin_eof():
    """stdin_to_socket catches OSError if shutdown(SHUT_WR) fails."""
    mock_sock = MagicMock(spec=socket.socket)
    mock_sock.shutdown.side_effect = OSError("already closed")
    # recv returns empty immediately so the main thread exits quickly
    mock_sock.recv.return_value = b""

    stdin = io.BytesIO(b"")
    stdout = io.BytesIO()

    relay(mock_sock, stdin, stdout)


def test_main_requires_socket_argument():
    """main() exits with code 1 when no arguments are provided."""
    with patch("sys.argv", ["mcp_bridge.py"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1


def test_main_connects_and_relays(tmp_path: Path):
    """main() connects to the socket and relays data."""
    socket_path = tmp_path / "test.sock"

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)

    def server_handler() -> None:
        conn, _ = server.accept()
        conn.sendall(b'{"result":"ok"}\n')
        conn.close()

    t = threading.Thread(target=server_handler)
    t.start()

    stdin_mock = MagicMock()
    stdin_mock.buffer = io.BytesIO(b"")
    stdout_mock = MagicMock()
    stdout_buf = io.BytesIO()
    stdout_mock.buffer = stdout_buf

    with (
        patch("sys.argv", ["mcp_bridge.py", str(socket_path)]),
        patch("docketeer_bubblewrap.mcp_bridge.sys") as mock_sys,
    ):
        mock_sys.argv = ["mcp_bridge.py", str(socket_path)]
        mock_sys.stdin.buffer = io.BytesIO(b"")
        mock_sys.stdout.buffer = stdout_buf
        mock_sys.stderr = MagicMock()
        main()

    t.join(timeout=5)
    server.close()

    assert stdout_buf.getvalue() == b'{"result":"ok"}\n'
