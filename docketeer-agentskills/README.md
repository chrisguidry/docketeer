# docketeer-agentskills

[Agent Skills](https://agentskills.io/specification) plugin for
[Docketeer](https://github.com/chrisguidry/docketeer).

Adds support for installing, managing, and using skills packaged as directories
with a `SKILL.md` file (YAML frontmatter + markdown instructions).

## Tools

| Tool | Description |
|------|-------------|
| `list_skills` | List installed skills with descriptions |
| `activate_skill` | Load a skill's full instructions |
| `install_skill` | Install a skill from a git repository |
| `uninstall_skill` | Remove an installed skill |

## How it works

Skills live in `{workspace}/skills/`. The plugin provides two levels of
progressive disclosure:

1. **System prompt** — skill names and descriptions are always available
2. **activate_skill** — loads the full SKILL.md body on demand

Skill files can be read directly with the workspace `read_file` and
`list_files` tools (e.g. `read_file("skills/my-skill/template.txt")`).

## Configuration

No configuration required. Skills are discovered automatically from the
`skills/` directory in the agent's workspace.
