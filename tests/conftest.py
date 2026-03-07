import ast
import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.timeout(1)


def workspace_members_list() -> list[str]:
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        config = tomllib.load(f)
    return config["tool"]["uv"]["workspace"]["members"]


@pytest.fixture()
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture()
def root_pyproject() -> dict:
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


@pytest.fixture()
def workspace_members() -> list[str]:
    return workspace_members_list()


@pytest.fixture()
def root_readme() -> str:
    return (REPO_ROOT / "README.md").read_text()


def package_pyproject(root: Path, member: str) -> dict:
    with open(root / member / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


_ENV_GET_METHODS = frozenset(
    {
        "get_str",
        "get_int",
        "get_path",
        "get_timedelta",
        "get_log_level",
    }
)

_ENV_DEPENDENCY_FUNCS = frozenset(
    {
        "EnvironmentStr",
        "EnvironmentInt",
        "EnvironmentTimedelta",
    }
)


def _is_env_get_call(node: ast.Call) -> bool:
    """Match `environment.get_str(...)` and `get_str(...)` (direct import)."""
    if isinstance(node.func, ast.Name) and node.func.id in _ENV_GET_METHODS:
        return True
    return (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "environment"
        and node.func.attr in _ENV_GET_METHODS
    )


def _is_env_dependency_call(node: ast.Call) -> bool:
    """Match `EnvironmentStr(...)` and similar."""
    return isinstance(node.func, ast.Name) and node.func.id in _ENV_DEPENDENCY_FUNCS


def _is_os_environ_get(node: ast.Call) -> bool:
    """Match `os.environ.get("DOCKETEER_...")` and `os.environ["DOCKETEER_..."]`."""
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "environ"
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "os"
    )


def _is_discover_one_call(node: ast.Call) -> bool:
    """Match `discover_one("docketeer.x", "ENV_NAME")`."""
    return isinstance(node.func, ast.Name) and node.func.id == "discover_one"


_DOCKETEER_PREFIX = "DOCKETEER_"


def env_vars_in_source(pkg_dir: Path) -> set[str]:
    names: set[str] = set()
    for py_file in (pkg_dir / "src").rglob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            if _is_env_get_call(node) or _is_env_dependency_call(node):
                if not node.args:
                    continue
                first_arg = node.args[0]
                if isinstance(first_arg, ast.Constant) and isinstance(
                    first_arg.value, str
                ):
                    names.add(first_arg.value)

            elif _is_os_environ_get(node):
                if not node.args:
                    continue
                first_arg = node.args[0]
                if (
                    isinstance(first_arg, ast.Constant)
                    and isinstance(first_arg.value, str)
                    and first_arg.value.startswith(_DOCKETEER_PREFIX)
                ):
                    names.add(first_arg.value.removeprefix(_DOCKETEER_PREFIX))

            elif _is_discover_one_call(node):
                if len(node.args) < 2:
                    continue
                second_arg = node.args[1]
                if isinstance(second_arg, ast.Constant) and isinstance(
                    second_arg.value, str
                ):
                    names.add(second_arg.value)

    return names


_README_ENV_VAR_PATTERN = re.compile(r"DOCKETEER_[A-Z_]+")


def env_vars_in_readme(readme_path: Path) -> set[str]:
    text = readme_path.read_text()
    return set(_README_ENV_VAR_PATTERN.findall(text))


def all_source_env_vars() -> list[tuple[str, str]]:
    """(member, "DOCKETEER_X") for every env var read in source."""
    cases = []
    for member in workspace_members_list():
        for var in sorted(env_vars_in_source(REPO_ROOT / member)):
            cases.append((member, f"DOCKETEER_{var}"))
    return cases


def all_readme_env_vars() -> list[tuple[str, str]]:
    """(member, "DOCKETEER_X") for every env var mentioned in a README."""
    cases = []
    for member in workspace_members_list():
        readme_path = REPO_ROOT / member / "README.md"
        for var in sorted(env_vars_in_readme(readme_path)):
            cases.append((member, var))
    return cases
