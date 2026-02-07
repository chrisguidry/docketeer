#!/usr/bin/env python3
"""Determine which workspace packages need testing based on changed files.

Reads workspace members from the root pyproject.toml, builds a reverse
dependency map from each member's pyproject.toml, then uses git diff to
figure out which packages are affected by the current change.

Trigger rules (matching .pre-commit-config.yaml):
  - Root-level file changes (not inside a member dir) → all packages
  - Changes in <member>/src/ → that member + reverse dependents
  - Changes in <member>/tests/ or <member>/pyproject.toml → just that member

Outputs to $GITHUB_OUTPUT (or stdout if not set):
  matrix=["docketeer", "docketeer-web", ...]
  has-packages=true|false
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path


def get_workspace_members(root: Path) -> list[str]:
    with open(root / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    return data["tool"]["uv"]["workspace"]["members"]


def get_workspace_dependencies(root: Path, member: str) -> list[str]:
    pyproject = root / member / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    deps: list[str] = []
    for dep in data.get("project", {}).get("dependencies", []):
        name = dep.split(">")[0].split("<")[0].split("=")[0].split("[")[0].strip()
        deps.append(name)
    return deps


def build_reverse_deps(
    root: Path,
    members: list[str],
) -> dict[str, set[str]]:
    reverse: dict[str, set[str]] = {m: set() for m in members}
    for member in members:
        for dep in get_workspace_dependencies(root, member):
            if dep in reverse:
                reverse[dep].add(member)
    return reverse


def get_changed_files(base_ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", base_ref],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.strip().splitlines() if line]


def compute_affected(
    changed_files: list[str],
    members: list[str],
    reverse_deps: dict[str, set[str]],
) -> list[str]:
    affected: set[str] = set()

    for path in changed_files:
        matched_member = None
        for member in members:
            if path.startswith(f"{member}/"):
                matched_member = member
                break

        if matched_member is None:
            return sorted(members)

        relative = path[len(matched_member) + 1 :]

        if relative.startswith("src/"):
            affected.add(matched_member)
            affected.update(reverse_deps.get(matched_member, set()))
        else:
            affected.add(matched_member)

    return sorted(affected)


def main() -> None:
    root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )

    if len(sys.argv) < 2:
        print("Usage: affected-packages.py <base-ref>", file=sys.stderr)
        sys.exit(1)

    base_ref = sys.argv[1]

    members = get_workspace_members(root)
    reverse_deps = build_reverse_deps(root, members)

    if base_ref == "0" * 40:
        affected = sorted(members)
    else:
        changed_files = get_changed_files(base_ref)
        if not changed_files:
            affected = []
        else:
            affected = compute_affected(changed_files, members, reverse_deps)

    matrix_json = json.dumps(affected)
    has_packages = "true" if affected else "false"

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"matrix={matrix_json}\n")
            f.write(f"has-packages={has_packages}\n")
    else:
        print(f"matrix={matrix_json}")
        print(f"has-packages={has_packages}")


if __name__ == "__main__":
    main()
