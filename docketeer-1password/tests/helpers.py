"""Test doubles for the 1Password op CLI."""

from dataclasses import dataclass
from unittest.mock import AsyncMock


@dataclass
class OpResponse:
    """A single response from the op CLI."""

    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


@dataclass
class OpCall:
    """A captured call to the op CLI."""

    args: tuple[object, ...]
    kwargs: dict[str, object]


class OpCLI:
    """Test double for the op CLI subprocess.

    Set up responses by calling the instance with strings (for success responses)
    or OpResponse objects (for custom return codes and stderr).  After the test
    runs, inspect ``calls`` to verify the commands that were issued.

    Usage::

        def test_something(vault, op_cli):
            op_cli("first response", "second response")
            result = await vault.list_secrets()
            assert op_cli.calls[0].args[1] == "vault"
    """

    def __init__(self) -> None:
        self.calls: list[OpCall] = []
        self._responses: list[OpResponse] = []
        self._index = 0

    def __call__(self, *responses: str | OpResponse) -> None:
        for r in responses:
            if isinstance(r, str):
                self._responses.append(OpResponse(stdout=r))
            else:
                self._responses.append(r)

    async def exec(self, *args: object, **kwargs: object) -> AsyncMock:
        """Fake ``asyncio.create_subprocess_exec`` that returns queued responses."""
        self.calls.append(OpCall(args=args, kwargs=kwargs))
        response = self._responses[self._index]
        self._index += 1
        proc = AsyncMock()
        proc.communicate.return_value = (
            response.stdout.encode(),
            response.stderr.encode(),
        )
        proc.returncode = response.returncode
        return proc
