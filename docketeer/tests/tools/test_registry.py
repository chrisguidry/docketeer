"""Tests for tool registry, schema generation, path safety, and param docs."""

from pathlib import Path
from unittest.mock import patch

import pytest

from docketeer.tools import (
    ToolContext,
    ToolRegistry,
    _load_tool_plugins,
    _parse_param_docs,
    _safe_path,
    _schema_from_hints,
)


def test_tool_registration():
    reg = ToolRegistry()

    @reg.tool
    async def greet(ctx: ToolContext, name: str) -> str:
        """Say hello.

        name: person to greet
        """
        return f"Hello {name}"  # pragma: no cover

    assert "greet" in reg._tools
    assert reg._schemas["greet"].name == "greet"
    assert reg._schemas["greet"].description == "Say hello.\n\nname: person to greet"


def test_definitions_returns_all():
    reg = ToolRegistry()

    @reg.tool
    async def tool_a(ctx: ToolContext) -> str:
        """Tool A."""
        return "a"  # pragma: no cover

    @reg.tool
    async def tool_b(ctx: ToolContext) -> str:
        """Tool B."""
        return "b"  # pragma: no cover

    defs = reg.definitions()
    assert len(defs) == 2
    names = {d.name for d in defs}
    assert names == {"tool_a", "tool_b"}


async def test_execute_success():
    reg = ToolRegistry()

    @reg.tool
    async def echo(ctx: ToolContext, text: str) -> str:
        """Echo text."""
        return text

    result = await reg.execute("echo", {"text": "hi"}, ToolContext(workspace=Path(".")))
    assert result == "hi"


async def test_execute_unknown_tool():
    reg = ToolRegistry()
    result = await reg.execute("nope", {}, ToolContext(workspace=Path(".")))
    assert result == "Unknown tool: nope"


async def test_execute_tool_error():
    reg = ToolRegistry()

    @reg.tool
    async def boom(ctx: ToolContext) -> str:
        """Boom."""
        raise ValueError("kaboom")

    result = await reg.execute("boom", {}, ToolContext(workspace=Path(".")))
    assert "Error: ValueError: kaboom" in result


def test_schema_from_hints_types():
    async def fn(
        ctx: ToolContext, name: str, age: int, active: bool, score: float
    ) -> str:
        """Test.

        name: the name
        age: the age
        active: is active
        score: the score
        """
        return ""  # pragma: no cover

    schema = _schema_from_hints(fn)
    assert schema["properties"]["name"]["type"] == "string"
    assert schema["properties"]["age"]["type"] == "integer"
    assert schema["properties"]["active"]["type"] == "boolean"
    assert schema["properties"]["score"]["type"] == "number"


def test_schema_from_hints_list_of_strings():
    async def fn(ctx: ToolContext, items: list[str]) -> str:
        """Test.

        items: the items
        """
        return ""  # pragma: no cover

    schema = _schema_from_hints(fn)
    assert schema["properties"]["items"]["type"] == "array"
    assert schema["properties"]["items"]["items"] == {"type": "string"}


def test_schema_from_hints_optional_dict():
    async def fn(ctx: ToolContext, env: dict[str, str] | None = None) -> str:
        """Test.

        env: environment variables
        """
        return ""  # pragma: no cover

    schema = _schema_from_hints(fn)
    assert schema["properties"]["env"]["type"] == "object"
    assert schema["properties"]["env"]["additionalProperties"] == {"type": "string"}
    assert schema["properties"]["env"]["default"] is None


def test_schema_from_hints_dict_of_strings():
    async def fn(ctx: ToolContext, env: dict[str, str]) -> str:
        """Test.

        env: environment variables
        """
        return ""  # pragma: no cover

    schema = _schema_from_hints(fn)
    assert schema["properties"]["env"]["type"] == "object"
    assert schema["properties"]["env"]["additionalProperties"] == {"type": "string"}


def test_schema_from_hints_required_vs_default():
    async def fn(
        ctx: ToolContext, required_param: str, optional_param: str = "default"
    ) -> str:
        """Test."""
        return ""  # pragma: no cover

    schema = _schema_from_hints(fn)
    assert "required_param" in schema["required"]
    assert "optional_param" not in schema["required"]
    assert schema["properties"]["optional_param"]["default"] == "default"


def test_schema_from_hints_skips_ctx():
    async def fn(ctx: ToolContext, name: str) -> str:
        """Test."""
        return ""  # pragma: no cover

    schema = _schema_from_hints(fn)
    assert "ctx" not in schema["properties"]


def test_parse_param_docs():
    docstring = """Do something.

    name: the person name
    age: their age
    """
    result = _parse_param_docs(docstring)
    assert result == {"name": "the person name", "age": "their age"}


def test_parse_param_docs_stops_at_separator():
    docstring = """Do something.

    name: before separator
    ---
    age: after separator
    """
    result = _parse_param_docs(docstring)
    assert "name" in result
    assert "age" not in result


def test_parse_param_docs_skips_comments():
    docstring = """Do something.

    # This is a comment
    name: the name
    """
    result = _parse_param_docs(docstring)
    assert result == {"name": "the name"}


def test_parse_param_docs_skips_invalid_identifier():
    docstring = """Do something.

    valid_name: a good param
    123-bad: not a valid identifier
    also_valid: another param
    """
    result = _parse_param_docs(docstring)
    assert result == {"valid_name": "a good param", "also_valid": "another param"}
    assert "123-bad" not in result


def test_safe_path_within_workspace(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    result = _safe_path(workspace, "sub/file.txt")
    assert str(result).startswith(str(workspace.resolve()))


def test_safe_path_traversal_blocked(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with pytest.raises(ValueError, match="outside workspace"):
        _safe_path(workspace, "../../../etc/passwd")


def test_tool_registration_with_emoji():
    reg = ToolRegistry()

    @reg.tool(emoji=":mag:")
    async def search(ctx: ToolContext, query: str) -> str:
        """Search."""
        return ""  # pragma: no cover

    assert reg._schemas["search"].emoji == ":mag:"


def test_tool_registration_without_emoji():
    reg = ToolRegistry()

    @reg.tool
    async def plain(ctx: ToolContext) -> str:
        """Plain."""
        return ""  # pragma: no cover

    assert reg._schemas["plain"].emoji == ""


def test_emoji_for_registered_tool():
    reg = ToolRegistry()

    @reg.tool(emoji=":lock:")
    async def my_tool(ctx: ToolContext) -> str:
        """Tool."""
        return ""  # pragma: no cover

    assert reg.emoji_for("my_tool") == ":lock:"


def test_emoji_for_unknown_tool():
    reg = ToolRegistry()
    assert reg.emoji_for("nonexistent") == ""


def test_emoji_for_mcp_prefixed_name():
    reg = ToolRegistry()

    @reg.tool(emoji=":open_file_folder:")
    async def list_files(ctx: ToolContext) -> str:
        """List files."""
        return ""  # pragma: no cover

    assert reg.emoji_for("mcp__docketeer__list_files") == ":open_file_folder:"


def test_load_tool_plugins_delegates_to_discover_all():
    with patch("docketeer.tools.discover_all", return_value=[]) as mock:
        _load_tool_plugins()
    mock.assert_called_once_with("docketeer.tools")
