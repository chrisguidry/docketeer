"""Tests for skill management tools."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

from docketeer.tools import ToolContext, registry

from .conftest import make_skill


async def test_list_skills_none(tool_context: ToolContext):
    result = await registry.execute("list_skills", {}, tool_context)
    assert "No skills installed" in result


async def test_list_skills(tool_context: ToolContext, skills_dir: Path):
    make_skill(skills_dir, name="my-skill", description="Does things")
    result = await registry.execute("list_skills", {}, tool_context)
    assert "my-skill: Does things" in result


async def test_activate_skill(tool_context: ToolContext, skills_dir: Path):
    make_skill(skills_dir, name="my-skill", body="## Step 1\n\nDo the thing.")
    result = await registry.execute(
        "activate_skill", {"name": "my-skill"}, tool_context
    )
    assert "Step 1" in result
    assert "Do the thing." in result


async def test_activate_skill_not_found(tool_context: ToolContext, skills_dir: Path):
    result = await registry.execute(
        "activate_skill", {"name": "nonexistent"}, tool_context
    )
    assert "Skill not found" in result


async def test_activate_skill_invalid(tool_context: ToolContext, skills_dir: Path):
    bad_dir = skills_dir / "bad-skill"
    bad_dir.mkdir()
    (bad_dir / "SKILL.md").write_text("---\nname: bad-skill\n---\nbody")
    result = await registry.execute(
        "activate_skill", {"name": "bad-skill"}, tool_context
    )
    assert "Error loading skill" in result


async def test_read_skill_file(tool_context: ToolContext, skills_dir: Path):
    skill_dir = make_skill(skills_dir)
    scripts = skill_dir / "scripts"
    scripts.mkdir()
    (scripts / "run.py").write_text("print('hello')")
    result = await registry.execute(
        "read_skill_file",
        {"name": "test-skill", "path": "scripts/run.py"},
        tool_context,
    )
    assert "print('hello')" in result


async def test_read_skill_file_directory(tool_context: ToolContext, skills_dir: Path):
    skill_dir = make_skill(skills_dir)
    scripts = skill_dir / "scripts"
    scripts.mkdir()
    (scripts / "a.py").write_text("")
    (scripts / "b.py").write_text("")
    result = await registry.execute(
        "read_skill_file",
        {"name": "test-skill", "path": "scripts"},
        tool_context,
    )
    assert "a.py" in result
    assert "b.py" in result


async def test_read_skill_file_not_found(tool_context: ToolContext, skills_dir: Path):
    make_skill(skills_dir)
    result = await registry.execute(
        "read_skill_file",
        {"name": "test-skill", "path": "nonexistent.txt"},
        tool_context,
    )
    assert "File not found" in result


async def test_read_skill_file_skill_not_found(
    tool_context: ToolContext, skills_dir: Path
):
    result = await registry.execute(
        "read_skill_file", {"name": "nope", "path": "file.txt"}, tool_context
    )
    assert "Skill not found" in result


async def test_read_skill_file_path_traversal(
    tool_context: ToolContext, skills_dir: Path
):
    make_skill(skills_dir)
    result = await registry.execute(
        "read_skill_file",
        {"name": "test-skill", "path": "../../etc/passwd"},
        tool_context,
    )
    assert "outside the skill directory" in result


async def test_read_skill_file_binary(tool_context: ToolContext, skills_dir: Path):
    skill_dir = make_skill(skills_dir)
    (skill_dir / "data.bin").write_bytes(b"\x00\x01\x02\xff\xfe")
    result = await registry.execute(
        "read_skill_file",
        {"name": "test-skill", "path": "data.bin"},
        tool_context,
    )
    assert "Cannot read binary file" in result


async def test_install_skill_no_git(tool_context: ToolContext):
    with patch("docketeer_agentskills.tools.shutil.which", return_value=None):
        result = await registry.execute(
            "install_skill", {"url": "https://example.com/repo.git"}, tool_context
        )
    assert "git is not installed" in result


async def test_install_skill_already_exists(
    tool_context: ToolContext, skills_dir: Path
):
    make_skill(skills_dir, name="existing")
    result = await registry.execute(
        "install_skill",
        {"url": "https://example.com/existing.git", "name": "existing"},
        tool_context,
    )
    assert "already installed" in result


async def test_install_skill_clone_failure(tool_context: ToolContext, skills_dir: Path):
    with patch("docketeer_agentskills.tools.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 128
        mock_run.return_value.stderr = "fatal: repo not found"
        result = await registry.execute(
            "install_skill",
            {"url": "https://example.com/bad.git", "name": "bad"},
            tool_context,
        )
    assert "Failed to clone" in result
    assert not (skills_dir / "bad").exists()


async def test_install_skill_no_skill_md(tool_context: ToolContext, skills_dir: Path):
    def fake_clone(*args: Any, **_kwargs: Any) -> object:
        clone_dir = Path(args[0][5])
        clone_dir.mkdir(parents=True, exist_ok=True)
        (clone_dir / "README.md").write_text("hi")

        class FakeResult:
            returncode = 0
            stderr = ""

        return FakeResult()

    with patch("docketeer_agentskills.tools.subprocess.run", side_effect=fake_clone):
        result = await registry.execute(
            "install_skill",
            {"url": "https://example.com/no-skill-md.git", "name": "no-skill-md"},
            tool_context,
        )
    assert "does not contain a SKILL.md" in result
    assert not (skills_dir / "no-skill-md").exists()


async def test_install_skill_invalid_skill_md(
    tool_context: ToolContext, skills_dir: Path
):
    def fake_clone(*args: Any, **_kwargs: Any) -> object:
        clone_dir = Path(args[0][5])
        clone_dir.mkdir(parents=True, exist_ok=True)
        (clone_dir / "SKILL.md").write_text("---\nname: bad-meta\n---\nbody")

        class FakeResult:
            returncode = 0
            stderr = ""

        return FakeResult()

    with patch("docketeer_agentskills.tools.subprocess.run", side_effect=fake_clone):
        result = await registry.execute(
            "install_skill",
            {"url": "https://example.com/bad-meta.git", "name": "bad-meta"},
            tool_context,
        )
    assert "Invalid skill" in result
    assert not (skills_dir / "bad-meta").exists()


async def test_install_skill_success(tool_context: ToolContext, skills_dir: Path):
    def fake_clone(*args: Any, **_kwargs: Any) -> object:
        clone_dir = Path(args[0][5])
        clone_dir.mkdir(parents=True, exist_ok=True)
        (clone_dir / "SKILL.md").write_text(
            "---\nname: cool-skill\ndescription: Cool stuff\n---\nDo things"
        )

        class FakeResult:
            returncode = 0
            stderr = ""

        return FakeResult()

    with patch("docketeer_agentskills.tools.subprocess.run", side_effect=fake_clone):
        result = await registry.execute(
            "install_skill",
            {"url": "https://example.com/cool-skill.git"},
            tool_context,
        )
    assert "Installed skill 'cool-skill'" in result
    assert "Cool stuff" in result


async def test_install_skill_derives_name_from_url(
    tool_context: ToolContext, skills_dir: Path
):
    def fake_clone(*args: Any, **_kwargs: Any) -> object:
        clone_dir = Path(args[0][5])
        clone_dir.mkdir(parents=True, exist_ok=True)
        (clone_dir / "SKILL.md").write_text(
            "---\nname: my-repo\ndescription: From URL\n---\nbody"
        )

        class FakeResult:
            returncode = 0
            stderr = ""

        return FakeResult()

    with patch("docketeer_agentskills.tools.subprocess.run", side_effect=fake_clone):
        result = await registry.execute(
            "install_skill",
            {"url": "https://github.com/user/my-repo.git"},
            tool_context,
        )
    assert "Installed skill 'my-repo'" in result


async def test_install_skill_with_path(tool_context: ToolContext, skills_dir: Path):
    def fake_clone(*args: Any, **_kwargs: Any) -> object:
        clone_target = Path(args[0][5])  # git clone --depth 1 url TARGET
        clone_target.mkdir(parents=True, exist_ok=True)
        nested = clone_target / "deep" / "nested" / "humanizer"
        nested.mkdir(parents=True)
        (nested / "SKILL.md").write_text(
            "---\nname: humanizer\ndescription: Humanize text\n---\nMake it human"
        )
        (nested / "extra.txt").write_text("bonus file")

        class FakeResult:
            returncode = 0
            stderr = ""

        return FakeResult()

    with patch("docketeer_agentskills.tools.subprocess.run", side_effect=fake_clone):
        result = await registry.execute(
            "install_skill",
            {
                "url": "https://github.com/user/templates.git",
                "name": "humanizer",
                "path": "deep/nested/humanizer",
            },
            tool_context,
        )
    assert "Installed skill 'humanizer'" in result
    assert "Humanize text" in result
    assert (skills_dir / "humanizer" / "SKILL.md").exists()
    assert (skills_dir / "humanizer" / "extra.txt").exists()


async def test_install_skill_with_path_no_skill_md(
    tool_context: ToolContext, skills_dir: Path
):
    def fake_clone(*args: Any, **_kwargs: Any) -> object:
        clone_target = Path(args[0][5])
        clone_target.mkdir(parents=True, exist_ok=True)
        nested = clone_target / "some" / "dir"
        nested.mkdir(parents=True)
        (nested / "README.md").write_text("not a skill")

        class FakeResult:
            returncode = 0
            stderr = ""

        return FakeResult()

    with patch("docketeer_agentskills.tools.subprocess.run", side_effect=fake_clone):
        result = await registry.execute(
            "install_skill",
            {
                "url": "https://github.com/user/templates.git",
                "name": "bad",
                "path": "some/dir",
            },
            tool_context,
        )
    assert "does not contain a SKILL.md" in result
    assert not (skills_dir / "bad").exists()


async def test_install_skill_with_path_not_found(
    tool_context: ToolContext, skills_dir: Path
):
    def fake_clone(*args: Any, **_kwargs: Any) -> object:
        clone_target = Path(args[0][5])
        clone_target.mkdir(parents=True, exist_ok=True)

        class FakeResult:
            returncode = 0
            stderr = ""

        return FakeResult()

    with patch("docketeer_agentskills.tools.subprocess.run", side_effect=fake_clone):
        result = await registry.execute(
            "install_skill",
            {
                "url": "https://github.com/user/templates.git",
                "name": "missing",
                "path": "nonexistent/subdir",
            },
            tool_context,
        )
    assert "not found in repository" in result
    assert not (skills_dir / "missing").exists()


async def test_install_skill_with_path_derives_name(
    tool_context: ToolContext, skills_dir: Path
):
    def fake_clone(*args: Any, **_kwargs: Any) -> object:
        clone_target = Path(args[0][5])
        clone_target.mkdir(parents=True, exist_ok=True)
        nested = clone_target / "skills" / "my-tool"
        nested.mkdir(parents=True)
        (nested / "SKILL.md").write_text(
            "---\nname: my-tool\ndescription: A tool\n---\nbody"
        )

        class FakeResult:
            returncode = 0
            stderr = ""

        return FakeResult()

    with patch("docketeer_agentskills.tools.subprocess.run", side_effect=fake_clone):
        result = await registry.execute(
            "install_skill",
            {
                "url": "https://github.com/user/templates.git",
                "path": "skills/my-tool",
            },
            tool_context,
        )
    assert "Installed skill 'my-tool'" in result
    assert (skills_dir / "my-tool" / "SKILL.md").exists()


async def test_uninstall_skill(tool_context: ToolContext, skills_dir: Path):
    make_skill(skills_dir, name="doomed")
    assert (skills_dir / "doomed").exists()
    result = await registry.execute("uninstall_skill", {"name": "doomed"}, tool_context)
    assert "Removed skill 'doomed'" in result
    assert not (skills_dir / "doomed").exists()


async def test_uninstall_skill_not_found(tool_context: ToolContext, skills_dir: Path):
    result = await registry.execute(
        "uninstall_skill", {"name": "nonexistent"}, tool_context
    )
    assert "Skill not found" in result
