"""Tool registry and toolkit for the Docketeer agent."""

import asyncio
import inspect
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import FunctionType
from typing import Any, get_type_hints

import httpx

from docketeer import environment

log = logging.getLogger(__name__)

BRAVE_API_KEY = environment.get_str("BRAVE_API_KEY")


@dataclass
class ToolContext:
    workspace: Path
    username: str = ""
    room_id: str = ""
    on_people_write: Callable[[], None] | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Callable] = {}
        self._schemas: dict[str, dict] = {}

    def tool[F: FunctionType](self, fn: F) -> F:
        """Decorator that registers a tool and derives its schema."""
        name = fn.__name__
        schema = _schema_from_hints(fn)
        self._tools[name] = fn
        self._schemas[name] = {
            "name": name,
            "description": (fn.__doc__ or "").strip().split("\n")[0],
            "input_schema": schema,
        }
        return fn

    def definitions(self) -> list[dict]:
        """Return tool definitions for the Anthropic API."""
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


@registry.tool
async def list_files(ctx: ToolContext, path: str = "") -> str:
    """List files and directories in the workspace.

    path: relative path within workspace (empty string for root)
    """
    target = _safe_path(ctx.workspace, path)
    if not target.exists():
        return f"Directory not found: {path}"
    if not target.is_dir():
        return f"Not a directory: {path}"
    entries = sorted(target.iterdir())
    if not entries:
        return "(empty directory)"
    return "\n".join(f"{e.name}/" if e.is_dir() else e.name for e in entries)


@registry.tool
async def read_file(ctx: ToolContext, path: str) -> str:
    """Read contents of a text file in the workspace.

    path: relative path to the file
    """
    target = _safe_path(ctx.workspace, path)
    if not target.exists():
        return f"File not found: {path}"
    if target.is_dir():
        return f"Path is a directory: {path}"
    try:
        return target.read_text()
    except UnicodeDecodeError:
        return f"Cannot read binary file: {path}"


@registry.tool
async def write_file(ctx: ToolContext, path: str, content: str) -> str:
    """Write content to a text file in the workspace.

    path: relative path to the file
    content: text content to write
    """
    target = _safe_path(ctx.workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    if path.startswith("people/") and ctx.on_people_write:
        ctx.on_people_write()
    return f"Wrote {len(content)} bytes to {path}"


@registry.tool
async def delete_file(ctx: ToolContext, path: str) -> str:
    """Delete a file from the workspace.

    path: relative path to the file
    """
    target = _safe_path(ctx.workspace, path)
    if not target.exists():
        return f"File not found: {path}"
    if target.is_dir():
        return f"Cannot delete directories, only files: {path}"
    target.unlink()
    return f"Deleted {path}"


@registry.tool
async def search_files(ctx: ToolContext, query: str, path: str = "") -> str:
    """Search for text across files in the workspace.

    query: text to search for (case-insensitive)
    path: relative path to search within (empty string for all)
    """
    target = _safe_path(ctx.workspace, path)
    if not target.exists():
        return f"Directory not found: {path}"

    query_lower = query.lower()
    matches = []
    for file in sorted(target.rglob("*")):
        if not file.is_file():
            continue
        try:
            text = file.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue
        for line_num, line in enumerate(text.splitlines(), 1):
            if query_lower in line.lower():
                rel = file.relative_to(ctx.workspace.resolve())
                matches.append(f"{rel}:{line_num}:{line.rstrip()}")
                if len(matches) >= 50:
                    return "\n".join(matches)

    if not matches:
        return f"No matches for '{query}'"
    return "\n".join(matches)


def _journal_dir(workspace: Path) -> Path:
    return workspace / "journal"


def _journal_path_for_date(workspace: Path, date: str) -> Path:
    return _journal_dir(workspace) / f"{date}.md"


@registry.tool
async def journal_add(ctx: ToolContext, entry: str) -> str:
    """Add a timestamped entry to today's journal. Use [[wikilinks]] to reference workspace files.

    entry: text to append (e.g. "talked to [[people/chris]] about the project")
    """
    now = datetime.now().astimezone()
    date = now.strftime("%Y-%m-%d")
    time = now.strftime("%H:%M")
    path = _journal_path_for_date(ctx.workspace, date)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        path.write_text(f"# {date}\n\n- {time} | {entry}\n")
    else:
        with path.open("a") as f:
            f.write(f"- {time} | {entry}\n")

    return f"Added to journal at {date} {time}"


@registry.tool
async def journal_read(
    ctx: ToolContext, date: str = "", start: str = "", end: str = ""
) -> str:
    """Read journal entries. Defaults to today. Use date for a single day, or start/end for a range.

    date: read a specific day (ISO format, e.g. 2026-02-05)
    start: start of date range (ISO format)
    end: end of date range (ISO format)
    """
    journal_dir = _journal_dir(ctx.workspace)
    if not journal_dir.exists():
        return "No journal entries yet"

    if date:
        path = _journal_path_for_date(ctx.workspace, date)
        if not path.exists():
            return f"No journal for {date}"
        return path.read_text()

    if start or end:
        files = sorted(journal_dir.glob("*.md"))
        entries = []
        for path in files:
            file_date = path.stem
            if start and file_date < start:
                continue
            if end and file_date > end:
                continue
            entries.append(path.read_text())
        if not entries:
            return f"No journal entries for range {start}–{end}"
        return "\n\n".join(entries)

    # Default: today
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    path = _journal_path_for_date(ctx.workspace, today)
    if not path.exists():
        return f"No journal entries for today ({today})"
    return path.read_text()


@registry.tool
async def journal_search(ctx: ToolContext, query: str) -> str:
    """Search across all journal entries.

    query: text to search for (case-insensitive)
    """
    journal_dir = _journal_dir(ctx.workspace)
    if not journal_dir.exists():
        return "No journal entries yet"

    query_lower = query.lower()
    matches = []

    for path in sorted(journal_dir.glob("*.md")):
        file_date = path.stem
        for line in path.read_text().splitlines():
            if not line.startswith("- "):
                continue
            if query_lower in line.lower():
                matches.append(f"[{file_date}] {line}")
                if len(matches) >= 50:
                    return "\n".join(matches)

    if not matches:
        return f"No journal entries matching '{query}'"
    return "\n".join(matches)


@registry.tool
async def web_search(ctx: ToolContext, query: str, count: int = 5) -> str:
    """Search the web using Brave Search.

    query: search query
    count: number of results (default 5)
    """
    if not BRAVE_API_KEY:
        return (
            "Error: Brave Search API key not configured (set DOCKETEER_BRAVE_API_KEY)"
        )

    max_retries = 3
    async with httpx.AsyncClient() as client:
        for attempt in range(max_retries):
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": count},
                headers={"X-Subscription-Token": BRAVE_API_KEY},
                timeout=30,
            )
            if response.status_code == 429:
                retry_after = int(response.headers.get("retry-after", 1))
                log.info(
                    "Brave rate limited, retrying in %ds (attempt %d/%d)",
                    retry_after,
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(retry_after)
                continue
            if response.status_code == 401:
                return "Error: Brave Search API key is invalid"
            response.raise_for_status()
            break
        else:
            return "Error: Brave Search rate limit exceeded, try again shortly"

        data = response.json()

    results = data.get("web", {}).get("results", [])
    if not results:
        return f"No results for '{query}'"

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("url", "")
        desc = r.get("description", "")
        lines.append(f"{i}. {title}\n   {url}\n   {desc}")

    return "\n\n".join(lines)


@registry.tool
async def web_request(
    ctx: ToolContext, url: str, method: str = "GET", headers: str = "", body: str = ""
) -> str:
    """Make an HTTP request to a URL.

    url: the URL to request
    method: HTTP method (default GET)
    headers: optional JSON string of headers
    body: optional request body
    """
    parsed_headers = {}
    if headers:
        try:
            parsed_headers = json.loads(headers)
        except json.JSONDecodeError:
            return "Error: headers must be a valid JSON string"

    async with httpx.AsyncClient() as client:
        response = await client.request(
            method=method,
            url=url,
            headers=parsed_headers,
            content=body or None,
            timeout=30,
        )

    text = response.text
    if len(text) > 10_000:
        text = text[:10_000] + "\n... (truncated)"

    return f"HTTP {response.status_code}\n\n{text}"


@registry.tool
async def download_file(ctx: ToolContext, url: str, path: str) -> str:
    """Download a file from a URL to the workspace.

    url: the URL to download
    path: relative path in workspace to save the file
    """
    target = _safe_path(ctx.workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(url, timeout=60)
        response.raise_for_status()

    target.write_bytes(response.content)
    return f"Downloaded {len(response.content)} bytes to {path}"
