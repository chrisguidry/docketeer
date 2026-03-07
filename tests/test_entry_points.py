import re

from .conftest import REPO_ROOT, package_pyproject, workspace_members_list


def test_every_entry_point_group_in_readme():
    members = workspace_members_list()
    readme = (REPO_ROOT / "README.md").read_text()

    source_groups: set[str] = set()
    for member in members:
        pyproj = package_pyproject(REPO_ROOT, member)
        entry_points = pyproj.get("project", {}).get("entry-points", {})
        for group in entry_points:
            source_groups.add(group)

    readme_groups = set(re.findall(r"`(docketeer\.[a-z_.]+)`", readme))

    # Only compare entry point groups that actually exist in packages
    entry_point_style = {g for g in readme_groups if g.startswith("docketeer.")}
    assert source_groups <= entry_point_style, (
        f"Entry point groups in packages but not in README: "
        f"{source_groups - entry_point_style}"
    )
    assert entry_point_style <= source_groups, (
        f"Entry point groups in README but not in any package: "
        f"{entry_point_style - source_groups}"
    )
