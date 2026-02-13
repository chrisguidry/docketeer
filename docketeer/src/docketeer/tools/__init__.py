"""Tool registry and toolkit for the Docketeer agent."""

from __future__ import annotations

import inspect
import logging
import types
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from types import FunctionType
from typing import Any, get_args, get_origin, get_type_hints

from anthropic.types import ToolParam

from docketeer.executor import CommandExecutor
from docketeer.plugins import discover_all
from docketeer.prompt import CacheControl
from docketeer.vault import Vault

log = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """A tool available to the agent."""

    name: str
    description: str
    input_schema: dict[str, Any]
    emoji: str = ""
    cache_control: CacheControl | None = None

    def to_api_dict(self) -> ToolParam:
        d = ToolParam(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
        )
        if self.cache_control:
            d["cache_control"] = self.cache_control.to_api_dict()
        return d


@dataclass
class ToolContext:
    workspace: Path
    username: str = ""
    agent_username: str = ""
    room_id: str = ""
    thread_id: str = ""
    on_people_write: Callable[[], None] | None = None
    summarize: Callable[[str, str], Awaitable[str]] | None = None
    classify_response: Callable[[str, int, str], Awaitable[bool]] | None = None
    executor: CommandExecutor | None = None
    vault: Vault | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Callable] = {}
        self._schemas: dict[str, ToolDefinition] = {}

    def tool[F: FunctionType](self, fn: F | None = None, *, emoji: str = "") -> F:
        """Decorator that registers a tool and derives its schema.

        Supports both ``@registry.tool`` and ``@registry.tool(emoji=":mag:")``.
        """

        def _register(fn: F) -> F:
            name = fn.__name__
            schema = _schema_from_hints(fn)
            self._tools[name] = fn
            self._schemas[name] = ToolDefinition(
                name=name,
                description=inspect.cleandoc(fn.__doc__ or ""),
                input_schema=schema,
                emoji=emoji,
            )
            return fn

        if fn is not None:
            return _register(fn)
        return _register  # type: ignore[return-value]

    def emoji_for(self, name: str) -> str:
        """Look up the emoji for a registered tool.

        Handles MCP-prefixed names like ``mcp__docketeer__list_files``
        by stripping everything before the last ``__`` separator.
        """
        defn = self._schemas.get(name)
        if not defn and "__" in name:
            defn = self._schemas.get(name.rsplit("__", 1)[-1])
        return defn.emoji if defn else ""

    def definitions(self) -> list[ToolDefinition]:
        """Return tool definitions."""
        return list(self._schemas.values())

    async def execute(self, name: str, args: dict[str, Any], ctx: ToolContext) -> str:
        """Execute a tool by name, passing context and args."""
        fn = self._tools.get(name)
        if not fn:
            return f"Unknown tool: {name}"
        try:
            return await fn(ctx, **args)
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"


TYPE_MAP = {
    str: "string",
    int: "integer",
    bool: "boolean",
    float: "number",
}


def _schema_from_hints(fn: Callable) -> dict:
    """Derive a JSON Schema input_schema from a tool function's type hints and docstring."""
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    param_descriptions = _parse_param_docs(fn.__doc__ or "")

    properties = {}
    required = []

    for param_name, param in sig.parameters.items():
        if param_name == "ctx":
            continue
        hint = hints.get(param_name, str)
        # Unwrap Optional / X | None to the inner type
        if get_origin(hint) is types.UnionType:
            hint = next(a for a in get_args(hint) if a is not type(None))
        prop: dict[str, Any]
        if get_origin(hint) is list:
            item_type = get_args(hint)[0] if get_args(hint) else str
            prop = {
                "type": "array",
                "items": {"type": TYPE_MAP.get(item_type, "string")},
            }
        elif get_origin(hint) is dict:
            args = get_args(hint)
            value_type = args[1] if len(args) > 1 else str
            prop = {
                "type": "object",
                "additionalProperties": {"type": TYPE_MAP.get(value_type, "string")},
            }
        else:
            prop = {"type": TYPE_MAP.get(hint, "string")}

        if param_name in param_descriptions:
            prop["description"] = param_descriptions[param_name]

        if param.default is inspect.Parameter.empty:
            required.append(param_name)
        else:
            prop["default"] = param.default

        properties[param_name] = prop

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _parse_param_docs(docstring: str) -> dict[str, str]:
    """Parse 'param_name: description' lines from a docstring."""
    descriptions = {}
    for line in docstring.split("\n")[1:]:
        line = line.strip()
        if ":" in line and not line.startswith("#"):
            name, _, desc = line.partition(":")
            name = name.strip()
            desc = desc.strip()
            if name.isidentifier() and desc:
                descriptions[name] = desc
        elif line.startswith("---"):
            break
    return descriptions


def _safe_path(workspace: Path, path: str) -> Path:
    """Resolve path and ensure it's within workspace."""
    resolved = (workspace / path).resolve()
    if not resolved.is_relative_to(workspace.resolve()):
        raise ValueError(f"Path '{path}' is outside workspace")
    return resolved


registry = ToolRegistry()


def _load_tool_plugins() -> None:
    """Discover and load tool plugins registered via the docketeer.tools entry_point group."""
    discover_all("docketeer.tools")


import docketeer.tools.executor as _executor  # noqa: E402, F401
import docketeer.tools.journal as _journal  # noqa: E402, F401
import docketeer.tools.vault as _vault  # noqa: E402, F401
import docketeer.tools.workspace as _workspace  # noqa: E402, F401

_load_tool_plugins()
