import pytest

from .conftest import (
    REPO_ROOT,
    all_readme_env_vars,
    all_source_env_vars,
    env_vars_in_readme,
    env_vars_in_source,
    workspace_members_list,
)

DYNAMIC_ENV_VARS: dict[str, set[str]] = {
    "docketeer-deepinfra": {
        "DOCKETEER_DEEPINFRA_MODEL_SMART",
        "DOCKETEER_DEEPINFRA_MODEL_BALANCED",
        "DOCKETEER_DEEPINFRA_MODEL_FAST",
    },
}


def _dynamic_env_var_cases() -> list[tuple[str, str]]:
    return [
        (member, var)
        for member, vars in sorted(DYNAMIC_ENV_VARS.items())
        for var in sorted(vars)
    ]


@pytest.fixture(scope="module")
def all_known_env_vars() -> set[str]:
    known: set[str] = set()
    for member in workspace_members_list():
        for var in env_vars_in_source(REPO_ROOT / member):
            known.add(f"DOCKETEER_{var}")
    for vars in DYNAMIC_ENV_VARS.values():
        known |= vars
    return known


# --- source -> readme: every env var in source must be documented ---


@pytest.mark.parametrize(("member", "env_var"), all_source_env_vars())
def test_source_env_var_in_readme(member: str, env_var: str):
    readme_vars = env_vars_in_readme(REPO_ROOT / member / "README.md")
    assert env_var in readme_vars, f"{member}/README.md is missing {env_var}"


@pytest.mark.parametrize(("member", "env_var"), _dynamic_env_var_cases())
def test_dynamic_env_var_in_readme(member: str, env_var: str):
    readme_vars = env_vars_in_readme(REPO_ROOT / member / "README.md")
    assert env_var in readme_vars, f"{member}/README.md is missing {env_var}"


# --- readme -> source: every env var in a readme must exist somewhere ---


@pytest.mark.parametrize(("member", "env_var"), all_readme_env_vars())
def test_readme_env_var_in_source(
    member: str,
    env_var: str,
    all_known_env_vars: set[str],
):
    assert env_var in all_known_env_vars, (
        f"{member}/README.md references {env_var} but no package reads it"
    )
