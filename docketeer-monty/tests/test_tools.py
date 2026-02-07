"""Tests for the Monty sandboxed Python execution tool."""

from docketeer.tools import ToolContext, registry
from docketeer_monty.tools import (
    _available_tools,
    _build_external_functions,
    _format_output,
)


def test_available_tools_excludes_run_python():
    tools = _available_tools()
    names = [t["name"] for t in tools]
    assert "run_python" not in names
    assert len(names) > 0


def test_build_external_functions_empty(tool_context: ToolContext):
    assert _build_external_functions([], tool_context) == {}


async def test_build_external_functions_wrapper(tool_context: ToolContext):
    (tool_context.workspace / "test.txt").write_text("via wrapper")
    fns = _build_external_functions(_available_tools(), tool_context)
    assert "read_file" in fns
    result = await fns["read_file"]("test.txt")
    assert result == "via wrapper"


# --- _format_output ---


def test_format_output_expression_only():
    assert _format_output(42, []) == "42"


def test_format_output_stdout_only():
    assert _format_output(None, ["hello\n"]) == "[stdout]\nhello\n"


def test_format_output_expression_and_stdout():
    assert _format_output(42, ["hi\n"]) == "42\n[stdout]\nhi\n"


def test_format_output_nothing():
    assert _format_output(None, []) == "(no output)"


# --- run_python ---


async def test_run_python_simple_expression(tool_context: ToolContext):
    result = await registry.execute("run_python", {"code": "2 + 2"}, tool_context)
    assert result == "4"


async def test_run_python_string_expression(tool_context: ToolContext):
    result = await registry.execute(
        "run_python", {"code": "'hello ' + 'world'"}, tool_context
    )
    assert result == "hello world"


async def test_run_python_none_result(tool_context: ToolContext):
    result = await registry.execute("run_python", {"code": "x = 1"}, tool_context)
    assert result == "(no output)"


async def test_run_python_print_captured(tool_context: ToolContext):
    result = await registry.execute(
        "run_python", {"code": 'print("hello")\nprint("world")'}, tool_context
    )
    assert "[stdout]" in result
    assert "hello" in result
    assert "world" in result


async def test_run_python_print_with_expression(tool_context: ToolContext):
    result = await registry.execute(
        "run_python", {"code": 'print("debug info")\n42'}, tool_context
    )
    assert result.startswith("42")
    assert "[stdout]" in result
    assert "debug info" in result


async def test_run_python_syntax_error(tool_context: ToolContext):
    result = await registry.execute("run_python", {"code": "if"}, tool_context)
    assert result.startswith("Syntax error:")


async def test_run_python_runtime_error(tool_context: ToolContext):
    result = await registry.execute("run_python", {"code": "1 / 0"}, tool_context)
    assert "Runtime error:" in result
    assert "ZeroDivisionError" in result


async def test_run_python_runtime_error_preserves_prior_stdout(
    tool_context: ToolContext,
):
    result = await registry.execute(
        "run_python", {"code": 'print("before")\n1 / 0'}, tool_context
    )
    assert "[stdout]" in result
    assert "before" in result
    assert "Runtime error:" in result


async def test_run_python_reads_file(tool_context: ToolContext):
    (tool_context.workspace / "greeting.txt").write_text("hello from workspace")
    result = await registry.execute(
        "run_python",
        {"code": 'await read_file("greeting.txt")'},
        tool_context,
    )
    assert result == "hello from workspace"


async def test_run_python_writes_and_reads_file(tool_context: ToolContext):
    code = 'await write_file("out.txt", "written by monty")\nawait read_file("out.txt")'
    result = await registry.execute("run_python", {"code": code}, tool_context)
    assert result == "written by monty"
    assert (tool_context.workspace / "out.txt").read_text() == "written by monty"


async def test_run_python_computes_with_results(tool_context: ToolContext):
    (tool_context.workspace / "a.txt").write_text("hello")
    (tool_context.workspace / "b.txt").write_text("world")
    code = """
a = await read_file("a.txt")
b = await read_file("b.txt")
f"{a} {b}"
"""
    result = await registry.execute("run_python", {"code": code}, tool_context)
    assert result == "hello world"
