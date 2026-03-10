"""Workspace hooks — file-based configuration via special directories.

Writing, editing, or deleting files in hook-registered directories triggers
plugin-registered callbacks that perform backend operations (scheduling,
antenna tuning, MCP config). Hooks split file operations into two phases:

- **validate**: check content validity, return enrichments (no side effects)
- **commit**: perform the actual backend operation (after file is on disk)

The hooks also support a scan() method for reconciling runtime state with
workspace files on startup and after commands.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, runtime_checkable

import yaml

log = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)", re.DOTALL)


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content.

    Returns (metadata_dict, body_text). If no frontmatter is found,
    returns an empty dict and the full content as body.
    """
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}, content

    raw_yaml = m.group(1)
    body = m.group(2)

    meta = yaml.safe_load(raw_yaml)
    if not isinstance(meta, dict):
        return {}, content

    return meta, body


def strip_frontmatter(content: str) -> str:
    """Return just the body text with frontmatter removed."""
    _, body = parse_frontmatter(content)
    return body


def render_frontmatter(meta: dict, body: str) -> str:
    """Render a metadata dict and body back into frontmatter-delimited content."""
    raw = yaml.dump(meta, default_flow_style=False, sort_keys=False).rstrip("\n")
    if body:
        return f"---\n{raw}\n---\n{body}"
    return f"---\n{raw}\n---\n"


@dataclass
class HookResult:
    """Result from a hook's validate call."""

    message: str
    updated_content: str | None = None


@runtime_checkable
class WorkspaceHook(Protocol):
    """A hook that reacts to file operations in a workspace directory.

    File writes are split into two phases:
    - validate: check content, return enrichments, no side effects
    - commit: perform the backend operation after file is safely on disk
    """

    prefix: PurePosixPath

    async def validate(self, path: PurePosixPath, content: str) -> HookResult | None:
        """Validate content before the file is written.

        Returns None if the hook doesn't care about this specific file.
        Returns a HookResult with a message and optionally enriched content.
        Raises ValueError for invalid content (file will not be written).
        """
        ...  # pragma: no cover

    async def commit(self, path: PurePosixPath, content: str) -> None:
        """Perform the backend operation after the file is written to disk.

        Only called when validate returned a non-None result. The content
        passed is the final on-disk content (including any enrichments).
        """
        ...  # pragma: no cover

    async def on_delete(self, path: PurePosixPath) -> str | None:
        """Called after a file is deleted under this prefix.

        Returns a status message, or None for default delete messaging.
        """
        ...  # pragma: no cover

    async def scan(self, workspace: Path) -> None:
        """Reconcile runtime state with files on disk.

        Called at startup and after command execution. Must be idempotent.
        """
        ...  # pragma: no cover


class HookRegistry:
    """Holds registered hooks and provides lookup by path."""

    def __init__(self) -> None:
        self._hooks: list[WorkspaceHook] = []

    def register(self, hook: WorkspaceHook) -> None:
        self._hooks.append(hook)

    def find_hook(self, path: PurePosixPath) -> WorkspaceHook | None:
        """Find the hook whose prefix matches the given path."""
        for hook in self._hooks:
            if path.parts[: len(hook.prefix.parts)] == hook.prefix.parts:
                return hook
        return None

    async def scan_all(self, workspace: Path) -> None:
        """Call scan() on every registered hook."""
        for hook in self._hooks:
            log.info("Scanning hook prefix '%s'", hook.prefix)
            try:
                await hook.scan(workspace)
            except Exception:
                log.warning(
                    "Hook scan failed for prefix '%s'",
                    hook.prefix,
                    exc_info=True,
                )


hook_registry = HookRegistry()
