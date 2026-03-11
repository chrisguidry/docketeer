"""Plugin discovery via entry point groups."""

import logging
import os
from importlib.metadata import EntryPoint, entry_points
from typing import Any

log = logging.getLogger(__name__)


class PluginUnavailable(Exception):
    """Raised by null-object implementations when no real plugin is installed."""


def discover_all(group: str) -> list[Any]:
    """Load all entry points for a plugin group, skipping any that fail."""
    loaded = []
    for ep in entry_points(group=group):
        try:
            loaded.append(ep.load())
        except Exception:
            log.warning("Failed to load %s plugin: %s", group, ep.name, exc_info=True)
    return loaded


def discover_one(group: str, env_name: str, *, default: str = "") -> EntryPoint | None:
    """Find the single active entry point for a plugin group.

    If exactly one plugin is installed, it's auto-selected. If multiple are
    installed, ``DOCKETEER_{env_name}`` must name which one to use. When
    ``default`` is provided and matches an installed plugin, it is used as
    the fallback when no env var is set. Returns ``None`` when no plugins
    are installed.
    """
    eps = list(entry_points(group=group))

    if not eps:
        return None

    if len(eps) == 1:
        return eps[0]

    selected = os.environ.get(f"DOCKETEER_{env_name}")
    if selected:
        for ep in eps:
            if ep.name == selected:
                return ep

    if default:
        for ep in eps:
            if ep.name == default:
                return ep

    names = ", ".join(sorted(ep.name for ep in eps))
    raise RuntimeError(
        f"Multiple {group} plugins installed ({names}). "
        f"Set DOCKETEER_{env_name} to choose one."
    )


def discover_explicit(group: str, env_name: str) -> EntryPoint | None:
    """Find an explicitly selected entry point for an optional plugin group.

    Returns ``None`` when ``DOCKETEER_{env_name}`` is unset. When set, the
    value must match an installed plugin name or a RuntimeError is raised.
    """
    selected = os.environ.get(f"DOCKETEER_{env_name}")
    if not selected:
        return None

    eps = list(entry_points(group=group))
    for ep in eps:
        if ep.name == selected:
            return ep

    names = ", ".join(sorted(ep.name for ep in eps)) or "none"
    raise RuntimeError(
        f"Unknown {group} plugin {selected!r}. Installed plugins: {names}."
    )
