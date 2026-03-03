"""Workspace file and directory tools."""

import os

from . import ToolContext, registry, safe_path


@registry.tool(emoji=":open_file_folder:")
async def list_files(ctx: ToolContext, path: str = "") -> str:
    """List files and directories in the workspace.

    path: relative path within workspace (empty string for root)
    """
    target = safe_path(ctx.workspace, path)
    if not target.exists():
        return f"Directory not found: {path}"
    if not target.is_dir():
        return f"Not a directory: {path}"
    entries = sorted(target.iterdir())
    if not entries:
        return "(empty directory)"
    lines: list[str] = []
    for e in entries:
        if e.is_symlink():
            link_target = os.readlink(e)
            lines.append(f"{e.name} -> {link_target}")
        elif e.is_dir():
            lines.append(f"{e.name}/")
        else:
            lines.append(e.name)
    return "\n".join(lines)


@registry.tool(emoji=":open_file_folder:")
async def read_file(ctx: ToolContext, path: str) -> str:
    """Read contents of a text file in the workspace.

    path: relative path to the file
    """
    target = safe_path(ctx.workspace, path)
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
    """Write content to a text file in the workspace. For editing existing
    files, prefer edit_file — it's safer and uses fewer tokens.

    path: relative path to the file
    content: text content to write
    """
    target = safe_path(ctx.workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    await ctx.search.index_file(path, content)
    return f"Wrote {len(content)} bytes to {path}"


@registry.tool(emoji=":open_file_folder:")
async def edit_file(
    ctx: ToolContext,
    path: str,
    old_string: str,
    new_string: str,
) -> str:
    """Edit an existing text file by replacing a specific string. The
    old_string must appear exactly once in the file — this ensures you're
    editing the right location and catches stale reads. Use read_file first
    to see the current content.

    To insert text, include surrounding content in both old_string and
    new_string. To delete text, pass an empty new_string.

    path: relative path to the file
    old_string: text to find (must match exactly once)
    new_string: replacement text (empty string to delete the match)
    """
    target = safe_path(ctx.workspace, path)
    if not target.exists():
        return f"File not found: {path}"
    if not old_string:
        return "old_string must not be empty"
    content = target.read_text()
    count = content.count(old_string)
    if count == 0:
        return f"old_string not found in {path}"
    if count > 1:
        return f"old_string appears {count} times in {path} (must be unique)"
    updated = content.replace(old_string, new_string, 1)
    target.write_text(updated)
    await ctx.search.index_file(path, updated)
    return f"Edited {path}"


@registry.tool(emoji=":open_file_folder:")
async def delete_file(ctx: ToolContext, path: str) -> str:
    """Delete a file from the workspace.

    path: relative path to the file
    """
    target = safe_path(ctx.workspace, path)
    if not target.exists():
        return f"File not found: {path}"
    if target.is_dir():
        return f"Cannot delete directories, only files: {path}"
    target.unlink()
    await ctx.search.remove_file(path)
    return f"Deleted {path}"


@registry.tool(emoji=":link:")
async def create_link(ctx: ToolContext, path: str, target: str) -> str:
    """Create a symbolic link in the workspace.

    path: relative path for the new symlink
    target: relative path the symlink should point to (must exist)
    """
    link_path = safe_path(ctx.workspace, path)
    target_path = safe_path(ctx.workspace, target)
    if not target_path.exists():
        return f"Target does not exist: {target}"
    # Check the unresolved path for existing symlinks
    unresolved = ctx.workspace / path
    if link_path.exists() or unresolved.is_symlink():
        return f"Path already exists: {path}"
    link_path.parent.mkdir(parents=True, exist_ok=True)
    rel_target = os.path.relpath(target_path, link_path.parent)
    unresolved.symlink_to(rel_target)
    return f"Created link {path} -> {rel_target}"


@registry.tool(emoji=":link:")
async def read_link(ctx: ToolContext, path: str) -> str:
    """Read the target of a symbolic link in the workspace.

    path: relative path to the symlink
    """
    # Validate path is within workspace, but check the unresolved path for symlink status
    safe_path(ctx.workspace, path)
    unresolved = ctx.workspace / path
    if not unresolved.is_symlink():
        return f"Not a symlink: {path}"
    return str(os.readlink(unresolved))


@registry.tool(emoji=":open_file_folder:")
async def search_files(ctx: ToolContext, query: str, path: str = "") -> str:
    """Search for text across files in the workspace.

    query: text to search for (case-insensitive)
    path: relative path to search within (empty string for all)
    """
    target = safe_path(ctx.workspace, path)
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
                    matches.append("(results truncated at 50 matches)")
                    return "\n".join(matches)

    if not matches:
        return f"No matches for '{query}'"
    return "\n".join(matches)
