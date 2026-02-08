"""Convention-based runtime discovery for the sandbox.

Scans PATH for known commands (node, uv, etc.) and produces mount/env
specs so the bubblewrap executor can expose them identically to both
the agent's run/shell tools and MCP server launches.
"""

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from docketeer.executor import Mount

SYSTEM_PREFIXES = ("/usr/", "/bin/", "/lib/", "/lib64/")


@dataclass
class RuntimeSpec:
    """Convention for finding a runtime on the host."""

    name: str
    probe_commands: list[str]
    cache_env_var: str


RUNTIMES: list[RuntimeSpec] = [
    RuntimeSpec("node", ["node", "npx", "npm"], "NPM_CONFIG_CACHE"),
    RuntimeSpec("python", ["uvx", "uv"], "UV_CACHE_DIR"),
]


@dataclass
class DiscoveredRuntime:
    """A runtime found on the host, ready for sandbox mounting."""

    spec: RuntimeSpec
    install_root: Path


@dataclass
class Toolshed:
    """Collection of discovered runtimes and their shared cache root."""

    runtimes: list[DiscoveredRuntime] = field(default_factory=list)
    cache_root: Path = Path()

    def mounts(self) -> list[Mount]:
        """Produce mounts for all discovered runtimes.

        Each runtime gets a read-only bind of its install root (same path
        inside the sandbox) and a writable cache directory at /cache/<name>.
        """
        result: list[Mount] = []
        for rt in self.runtimes:
            result.append(
                Mount(source=rt.install_root, target=rt.install_root, writable=False)
            )
            cache_dir = self.cache_root / rt.spec.name
            cache_dir.mkdir(parents=True, exist_ok=True)
            result.append(
                Mount(
                    source=cache_dir,
                    target=Path(f"/cache/{rt.spec.name}"),
                    writable=True,
                )
            )
        return result

    def env(self) -> dict[str, str]:
        """Produce environment variables for all discovered runtimes.

        Sets PATH to include runtime bin dirs ahead of the system dirs,
        and points each runtime's cache env var at /cache/<name>.
        """
        if not self.runtimes:
            return {}

        path_dirs: list[str] = []
        env: dict[str, str] = {}
        for rt in self.runtimes:
            bin_dir = rt.install_root / "bin"
            if bin_dir.is_dir():
                path_dirs.append(str(bin_dir))
            else:
                path_dirs.append(str(rt.install_root))
            env[rt.spec.cache_env_var] = f"/cache/{rt.spec.name}"

        path_dirs.extend(["/usr/local/bin", "/usr/bin", "/bin"])
        env["PATH"] = ":".join(path_dirs)
        return env


def _which_skipping_shims(cmd: str) -> str | None:
    """Find a command on PATH, skipping shim directories (pyenv, rbenv, etc.).

    Shim directories (named "shims") contain wrapper scripts that delegate
    to a version manager.  Those wrappers need the full version manager
    installation to function, so they're useless inside a sandbox.
    """
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    filtered = os.pathsep.join(d for d in path_dirs if Path(d).name != "shims")
    return shutil.which(cmd, path=filtered)


def _find_install_root(binary: Path) -> Path:
    """Walk from a resolved binary path to its installation root.

    If the binary sits in a bin/ directory, the install root is one level up
    (covers nvm, pyenv, etc.). Otherwise, the install root is the directory
    containing the binary.
    """
    if binary.parent.name == "bin":
        return binary.parent.parent
    return binary.parent


def discover(cache_root: Path) -> Toolshed:
    """Scan PATH for known runtimes and return a Toolshed.

    For each RuntimeSpec, tries its probe commands via shutil.which.
    Resolves to installation roots, skips anything already under system
    paths (those are already mounted by bubblewrap).
    """
    found: list[DiscoveredRuntime] = []
    seen_roots: set[Path] = set()

    for spec in RUNTIMES:
        for cmd in spec.probe_commands:
            which_result = _which_skipping_shims(cmd)
            if not which_result:
                continue

            resolved = Path(which_result).resolve()
            if any(str(resolved).startswith(p) for p in SYSTEM_PREFIXES):
                break

            root = _find_install_root(resolved)
            if root in seen_roots:
                break

            seen_roots.add(root)
            found.append(DiscoveredRuntime(spec=spec, install_root=root))
            break

    return Toolshed(runtimes=found, cache_root=cache_root)
