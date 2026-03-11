"""Sequential data migrations for docketeer.

Migrations are Python files in this package named ``NNN_description.py``
(e.g. ``001_backstage_to_workspace.py``). Each must define a ``run``
function with the signature ``(data_dir: Path, workspace: Path) -> None``.

Applied migration numbers are tracked in ``data_dir/migrations``.
"""

import importlib.util
import json
import logging
from pathlib import Path
from types import ModuleType

log = logging.getLogger(__name__)


def _applied_path(data_dir: Path) -> Path:
    return data_dir / "migrations"


def _load_applied(data_dir: Path) -> set[int]:
    path = _applied_path(data_dir)
    if not path.exists():
        return set()
    return set(json.loads(path.read_text()))


def _save_applied(data_dir: Path, applied: set[int]) -> None:
    path = _applied_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(applied)) + "\n")


def _discover() -> list[tuple[int, Path]]:
    """Find all migration files by scanning the package directory."""
    package_dir = Path(__file__).parent
    migrations: list[tuple[int, Path]] = []
    for path in sorted(package_dir.glob("[0-9]*.py")):
        number = int(path.stem.split("_", 1)[0])
        migrations.append((number, path))
    return migrations


def _load_module(path: Path) -> ModuleType:
    """Load a migration module from a file path."""
    module_name = f"docketeer.migrations._{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_migrations(data_dir: Path, workspace: Path) -> None:
    """Run all pending migrations in order."""
    applied = _load_applied(data_dir)
    for number, path in _discover():
        if number in applied:
            continue
        log.info("Running migration %03d: %s", number, path.stem)
        module = _load_module(path)
        module.run(data_dir, workspace)
        del module
        applied.add(number)
        _save_applied(data_dir, applied)
        log.info("Completed migration %03d", number)
