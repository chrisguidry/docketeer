#!/usr/bin/env python3
"""MCP bridge: relays stdin/stdout to a Unix domain socket.

Stdlib-only so it can run inside a minimal sandbox without any
pip-installed packages.

Usage: python3 mcp_bridge.py <socket_path>
"""

import contextlib
import socket
import sys
import threading
from typing import BinaryIO


def relay(
    sock: socket.socket,
    stdin: BinaryIO,
    stdout: BinaryIO,
) -> None:
    """Relay newline-delimited messages between stdin/stdout and a socket.

    Reads from stdin and forwards to the socket in a background thread.
    Reads from the socket and writes to stdout in the calling thread.
    Returns when the socket closes or stdin reaches EOF.
    """

    def stdin_to_socket() -> None:
        try:
            while True:
                line = stdin.readline()
                if not line:
                    break
                sock.sendall(line)
        except (BrokenPipeError, OSError):
            pass
        finally:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_WR)

    writer = threading.Thread(target=stdin_to_socket, daemon=True)
    writer.start()

    buf = b""
    try:
        while True:
            data = sock.recv(4096)
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                stdout.write(line + b"\n")
                stdout.flush()
    except (BrokenPipeError, OSError):
        pass
    finally:
        sock.close()


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: mcp_bridge.py <socket_path>", file=sys.stderr)
        sys.exit(1)

    socket_path = sys.argv[1]
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(socket_path)
    relay(sock, sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":  # pragma: no cover
    main()
