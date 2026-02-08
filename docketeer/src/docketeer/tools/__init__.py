"""Tool registry and toolkit for the Docketeer agent."""

import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from types import FunctionType
from typing import Any, get_type_hints

from anthropic.types import ToolParam

from docketeer.prompt import CacheControl

log = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """A tool available to the agent."""

    name: str
    description: str
    input_schema: dict[str, Any]
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
    room_id: str = ""
    on_people_write: Callable[[], None] | None = None
    summarize: Callable[[str, str], Awaitable[str]] | None = None
    classify_response: Callable[[str, int, str], Awaitable[bool]] | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Callable] = {}
        self._schemas: dict[str, ToolDefinition] = {}

    def tool[F: FunctionType](self, fn: F) -> F:
        """Decorator that registers a tool and derives its schema."""
        name = fn.__name__
        schema = _schema_from_hints(fn)
        self._tools[name] = fn
        self._schemas[name] = ToolDefinition(
            name=name,
            description=(fn.__doc__ or "").strip().split("\n")[0],
            input_schema=schema,
        )
        return fn

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
        json_type = TYPE_MAP.get(hint, "string")
        prop: dict[str, Any] = {"type": json_type}

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
    if not str(resolved).startswith(str(workspace.resolve())):
        raise ValueError(f"Path '{path}' is outside workspace")
    return resolved


registry = ToolRegistry()


def _load_tool_plugins() -> None:
    """Discover and load tool plugins registered via the docketeer.tools entry_point group."""
    from importlib.metadata import entry_points

    for ep in entry_points(group="docketeer.tools"):
        try:
            ep.load()
        except Exception:
            log.warning("Failed to load tool plugin: %s", ep.name, exc_info=True)


import docketeer.tools.journal as _journal  # noqa: E402, F401
import docketeer.tools.workspace as _workspace  # noqa: E402, F401

_load_tool_plugins()
