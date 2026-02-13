"""Sandboxed Python execution via Monty."""

import logging
from typing import Any, Literal

import pydantic_monty

from docketeer.tools import ToolContext, ToolDefinition, registry

log = logging.getLogger(__name__)


def _format_output(result: Any, stdout: list[str]) -> str:
    """Combine expression result and captured output into a single string."""
    parts = []
    if result is not None:
        parts.append(str(result))
    if stdout:
        parts.append(f"[stdout]\n{''.join(stdout)}")
    return "\n".join(parts) or "(no output)"


def _available_tools() -> list[ToolDefinition]:
    """Get tool definitions excluding run_python itself."""
    return [d for d in registry.definitions() if d.name != "run_python"]


def _build_external_functions(
    tools: list[ToolDefinition], ctx: ToolContext
) -> dict[str, Any]:
    """Build async wrapper functions that bridge Monty calls to the tool registry."""
    functions: dict[str, Any] = {}
    for tool in tools:
        param_names = list(tool.input_schema.get("properties", {}).keys())
        tool_name = tool.name

        async def wrapper(
            *args: Any,
            _name: str = tool_name,
            _params: list[str] = param_names,
            **kwargs: Any,
        ) -> str:
            call_args = dict(zip(_params, args, strict=False))
            call_args.update(kwargs)
            return await registry.execute(_name, call_args, ctx)

        functions[tool_name] = wrapper
    return functions


@registry.tool(emoji=":snake:")
async def run_python(ctx: ToolContext, code: str) -> str:
    """Run Python code in a sandboxed interpreter. Workspace tools are available as async functions (e.g. await read_file("path")).

    code: Python source code to execute
    """
    tools = _available_tools()
    fn_names = [t.name for t in tools]
    external_fns = _build_external_functions(tools, ctx)

    stdout: list[str] = []

    def on_print(stream: Literal["stdout"], text: str) -> None:
        stdout.append(text)

    try:
        m = pydantic_monty.Monty(
            code,
            external_functions=fn_names or None,
        )
        result = await pydantic_monty.run_monty_async(
            m,
            external_functions=external_fns or None,
            print_callback=on_print,
        )
    except pydantic_monty.MontySyntaxError as e:
        return f"Syntax error:\n{e}"
    except pydantic_monty.MontyRuntimeError as e:
        return _format_output(None, stdout) + f"\nRuntime error:\n{e}"

    return _format_output(result, stdout)
