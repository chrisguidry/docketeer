"""Tool registry and toolkit for the Docketeer agent."""

from __future__ import annotations

import inspect
import logging
import types
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import FunctionType
from typing import Any, get_args, get_origin, get_type_hints

from docketeer.executor import CommandExecutor, NullExecutor
from docketeer.plugins import discover_all
from docketeer.prompt import CacheControl
from docketeer.search import NullCatalog, SearchCatalog
from docketeer.vault import NullVault, Vault

log = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """A tool available to the agent."""

    name: str
    description: str
    input_schema: dict[str, Any]
    emoji: str = ""
    cache_control: CacheControl | None = None

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
        if self.cache_control:
            d["cache_control"] = self.cache_control.to_dict()
        return d


WRAP_UP_TOOL_NAME = "wrap_up_silently"


@dataclass
class ToolContext:
    workspace: Path
    username: str = ""
    agent_username: str = ""
    line: str = ""
    chat_room: str = ""
    thread_id: str = ""
    message_id: str = ""
    summarize: Callable[[str, str], Awaitable[str]] | None = None
    classify_response: Callable[[str, int, str], Awaitable[bool]] | None = None
    executor: CommandExecutor = field(default_factory=NullExecutor)
    vault: Vault = field(default_factory=NullVault)
    search: SearchCatalog = field(default_factory=NullCatalog)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Callable] = {}
        self._schemas: dict[str, ToolDefinition] = {}
        self._description_templates: dict[str, str] = {}
        self.template_vars: dict[str, str] = {}

    def tool[F: FunctionType](self, fn: F | None = None, *, emoji: str = "") -> F:
        """Decorator that registers a tool and derives its schema.

        Supports both ``@registry.tool`` and ``@registry.tool(emoji=":mag:")``.

        Tool descriptions are formatted with ``str.format_map(template_vars)``
        at definition time, not registration time — so executors can set
        ``template_vars`` after import. Use ``{var}`` for substitution and
        ``{{`` / ``}}`` to produce literal braces.
        """

        def _register(fn: F) -> F:
            name = fn.__name__
            schema = _schema_from_hints(fn)
            description = inspect.cleandoc(fn.__doc__ or "")
            self._tools[name] = fn
            self._description_templates[name] = description
            self._schemas[name] = ToolDefinition(
                name=name,
                description=description,
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
        """Return tool definitions, with template_vars applied to descriptions."""
        defs = list(self._schemas.values())
        template_vars = dict(self.template_vars)
        template_vars["tool_signatures"] = _build_tool_signatures(self)
        for d in defs:
            d.description = self._description_templates[d.name].format_map(
                template_vars
            )
        return defs

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


def _build_tool_signatures(registry: ToolRegistry) -> str:
    """Build a newline-separated list of async function signatures from real functions."""
    lines = []
    for name, fn in registry._tools.items():
        if name == "run_python":
            continue
        sig = inspect.signature(fn)
        params = [p for p in sig.parameters.values() if p.name != "ctx"]
        param_str = ", ".join(str(p) for p in params)
        lines.append(f"await {name}({param_str})")
    return "\n".join(lines)


def _type_to_schema(hint: Any) -> dict[str, Any]:
    """Convert a type hint to a JSON Schema fragment."""
    import typing

    origin = get_origin(hint)

    # Literal["a", "b"] → {"type": "string", "enum": ["a", "b"]}
    if origin is typing.Literal:
        values = list(get_args(hint))
        if values and all(isinstance(v, str) for v in values):
            return {"type": "string", "enum": values}
        return {"enum": values}

    # dict / dict[K, V]
    if hint is dict or origin is dict:
        args = get_args(hint)
        if args and len(args) > 1:
            return {
                "type": "object",
                "additionalProperties": _type_to_schema(args[1]),
            }
        return {"type": "object"}

    # TypedDict → object with typed properties
    if isinstance(hint, type) and _is_typeddict(hint):
        return _typeddict_to_schema(hint)

    return {"type": TYPE_MAP.get(hint, "string")}


def _is_typeddict(cls: type) -> bool:
    """Check if a class is a TypedDict."""
    return hasattr(cls, "__annotations__") and hasattr(cls, "__required_keys__")


def _typeddict_to_schema(cls: type) -> dict[str, Any]:
    """Convert a TypedDict to a JSON Schema object."""
    hints = get_type_hints(cls)
    required_keys = getattr(cls, "__required_keys__", set())
    properties = {name: _type_to_schema(hint) for name, hint in hints.items()}
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required_keys:
        schema["required"] = sorted(required_keys)
    return schema


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
                "items": _type_to_schema(item_type),
            }
        elif get_origin(hint) is dict:
            args = get_args(hint)
            value_type = args[1] if len(args) > 1 else str
            if get_origin(value_type) is types.UnionType:
                union_args = get_args(value_type)
                schemas = []
                for ua in union_args:
                    if ua is dict or get_origin(ua) is dict:
                        schemas.append({"type": "object"})
                    else:
                        schemas.append({"type": TYPE_MAP.get(ua, "string")})
                prop = {"type": "object", "additionalProperties": {"anyOf": schemas}}
            else:
                prop = {
                    "type": "object",
                    "additionalProperties": {
                        "type": TYPE_MAP.get(value_type, "string")
                    },
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


def safe_path(workspace: Path, path: str) -> Path:
    """Resolve path and ensure it's within workspace."""
    resolved = (workspace / path).resolve()
    if not resolved.is_relative_to(workspace.resolve()):
        raise ValueError(f"Path '{path}' is outside workspace")
    return resolved


registry = ToolRegistry()


def _load_tool_plugins() -> None:
    """Discover and load tool plugins registered via the docketeer.tools entry_point group."""
    discover_all("docketeer.tools")


# --- Lazy registration of domain tools ---
# These functions live in their domain modules to keep tools close to the
# code they operate on. We call them here after the registry is defined
# to avoid circular imports (domain modules import registry from this module).

from docketeer.executor import _register_executor_tools  # noqa: E402
from docketeer.vault import _register_vault_tools  # noqa: E402
from docketeer.workspace import _register_workspace_tools  # noqa: E402

_register_executor_tools()
_register_vault_tools()
_register_workspace_tools()
_load_tool_plugins()
