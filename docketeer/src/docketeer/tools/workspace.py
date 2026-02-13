"""Workspace file and directory tools."""

from . import ToolContext, _safe_path, registry


@registry.tool(emoji=":open_file_folder:")
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


@registry.tool(emoji=":open_file_folder:")
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


@registry.tool(emoji=":open_file_folder:")
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


@registry.tool(emoji=":open_file_folder:")
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


@registry.tool(emoji=":open_file_folder:")
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
