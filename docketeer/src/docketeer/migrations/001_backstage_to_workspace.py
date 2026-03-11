"""Migrate backstage JSON configs to workspace markdown.

Converts DATA_DIR/tunings/*.json and DATA_DIR/mcp/*.json into workspace
markdown files with YAML frontmatter, then removes the source JSON files.
Also moves per-tuning data directories (cursor, signal logs) to workspace.
"""

import json
import logging
from collections.abc import Callable
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


def _convert_tuning(data: dict) -> str:
    """Convert a tuning JSON dict to frontmatter markdown."""
    meta: dict = {}

    meta["band"] = data["band"]
    meta["topic"] = data["topic"]

    filters = data.get("filters", [])
    if filters:
        meta["filters"] = [
            {("field" if k == "path" else k): v for k, v in f.items()} for f in filters
        ]

    line = data.get("line", "")
    if line:
        meta["line"] = line

    secrets = data.get("secrets")
    if isinstance(secrets, dict):
        meta["secrets"] = secrets
    elif isinstance(secrets, str):
        meta["secrets"] = {"token": secrets}
    else:
        secret = data.get("secret", "")
        if secret:
            meta["secrets"] = {"token": secret}

    raw = yaml.dump(meta, default_flow_style=False, sort_keys=False).rstrip("\n")
    return f"---\n{raw}\n---\n"


def _convert_mcp(data: dict) -> str:
    """Convert an MCP server JSON dict to frontmatter markdown."""
    meta: dict = {}

    if "command" in data:
        meta["command"] = data["command"]
        if data.get("args"):
            meta["args"] = data["args"]
        if data.get("env"):
            meta["env"] = data["env"]
        if data.get("networkAccess"):
            meta["network_access"] = True

    if "url" in data:
        meta["url"] = data["url"]
        if data.get("headers"):
            meta["headers"] = data["headers"]

    if data.get("auth"):
        meta["auth"] = data["auth"]

    raw = yaml.dump(meta, default_flow_style=False, sort_keys=False).rstrip("\n")
    return f"---\n{raw}\n---\n"


def _migrate_directory(
    source_dir: Path,
    target_dir: Path,
    converter: Callable[[dict], str],
    label: str,
    *,
    migrate_data_dirs: bool = False,
) -> None:
    """Migrate all JSON files in source_dir to markdown in target_dir."""
    if not source_dir.is_dir():
        return

    for path in sorted(source_dir.glob("*.json")):
        name = path.stem
        target = target_dir / f"{name}.md"

        if target.exists():
            log.info("Skipping %s '%s': workspace file already exists", label, name)
            continue

        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            log.warning("Skipping %s '%s': could not parse JSON", label, name)
            continue

        content = converter(data)
        target_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        path.unlink()
        log.info("Migrated %s '%s' to workspace", label, name)

    if migrate_data_dirs:
        _migrate_data_dirs(source_dir, target_dir, label)


def _migrate_data_dirs(
    source_dir: Path,
    target_dir: Path,
    label: str,
) -> None:
    """Move per-item data directories from backstage to workspace."""
    for child in sorted(source_dir.iterdir()):
        if not child.is_dir():
            continue

        dest = target_dir / child.name
        if dest.exists():
            log.info(
                "Skipping %s data dir '%s': workspace dir already exists",
                label,
                child.name,
            )
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        child.rename(dest)
        log.info("Migrated %s data dir '%s' to workspace", label, child.name)


def run(data_dir: Path, workspace: Path) -> None:
    """Migrate backstage JSON configs to workspace markdown."""
    _migrate_directory(
        data_dir / "tunings",
        workspace / "tunings",
        _convert_tuning,
        "tuning",
        migrate_data_dirs=True,
    )
    _migrate_directory(
        data_dir / "mcp",
        workspace / "mcp",
        _convert_mcp,
        "mcp server",
    )
