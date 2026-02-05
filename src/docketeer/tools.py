"""Workspace file tools for Claude tool_use."""

from pathlib import Path
from typing import Any


WORKSPACE_TOOLS = [
    {
        "name": "list_files",
        "description": "List files and directories in the workspace. Use path='' for root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path within workspace (empty string for root)",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": "Read contents of a text file in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a text file in the workspace. Creates parent directories as needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write",
                },
            },
            "required": ["path", "content"],
        },
    },
]


class ToolExecutor:
    """Executes workspace tools with path sandboxing."""

    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()

    def _safe_path(self, path: str) -> Path:
        """Resolve path and ensure it's within workspace."""
        resolved = (self.workspace / path).resolve()
        if not str(resolved).startswith(str(self.workspace)):
            raise ValueError(f"Path '{path}' is outside workspace")
        return resolved

    async def execute(self, name: str, args: dict[str, Any]) -> str:
        """Execute a tool and return the result as a string."""
        try:
            if name == "list_files":
                return self._list_files(args.get("path", ""))
            elif name == "read_file":
                return self._read_file(args["path"])
            elif name == "write_file":
                return self._write_file(args["path"], args["content"])
            else:
                return f"Unknown tool: {name}"
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"

    def _list_files(self, path: str) -> str:
        target = self._safe_path(path)
        if not target.exists():
            return f"Directory not found: {path}"
        if not target.is_dir():
            return f"Not a directory: {path}"
        entries = sorted(target.iterdir())
        if not entries:
            return "(empty directory)"
        return "\n".join(f"{e.name}/" if e.is_dir() else e.name for e in entries)

    def _read_file(self, path: str) -> str:
        target = self._safe_path(path)
        if not target.exists():
            return f"File not found: {path}"
        if target.is_dir():
            return f"Path is a directory: {path}"
        try:
            return target.read_text()
        except UnicodeDecodeError:
            return f"Cannot read binary file: {path}"

    def _write_file(self, path: str, content: str) -> str:
        target = self._safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
