import re

import pytest

from .conftest import REPO_ROOT


@pytest.fixture()
def precommit_config() -> str:
    return (REPO_ROOT / ".pre-commit-config.yaml").read_text()


def test_readme_packages_table_matches_workspace(
    root_readme: str,
    workspace_members: list[str],
):
    pattern = re.compile(r"^\| \[([^\]]+)\]\(([^)]+)/\)")
    readme_packages = set()
    for line in root_readme.splitlines():
        m = pattern.match(line)
        if m:
            readme_packages.add(m.group(2))

    assert readme_packages == set(workspace_members)


def test_every_member_has_precommit_hook(
    workspace_members: list[str],
    precommit_config: str,
):
    hook_ids = set(re.findall(r"- id: pytest-(docketeer\S*)", precommit_config))
    expected = {m for m in workspace_members}
    assert hook_ids == expected


def test_every_member_in_dev_dependencies(root_pyproject: dict):
    dev_deps = root_pyproject["dependency-groups"]["dev"]
    docketeer_deps = {
        d for d in dev_deps if isinstance(d, str) and d.startswith("docketeer")
    }
    members = set(root_pyproject["tool"]["uv"]["workspace"]["members"])
    assert docketeer_deps == members


def test_every_member_in_uv_sources(root_pyproject: dict):
    sources = root_pyproject["tool"]["uv"]["sources"]
    docketeer_sources = {k for k in sources if k.startswith("docketeer")}
    members = set(root_pyproject["tool"]["uv"]["workspace"]["members"])
    assert docketeer_sources == members


def test_every_member_in_known_first_party(root_pyproject: dict):
    known = set(root_pyproject["tool"]["ruff"]["lint"]["isort"]["known-first-party"])
    members = root_pyproject["tool"]["uv"]["workspace"]["members"]
    expected = {m.replace("-", "_") for m in members}
    assert known == expected
