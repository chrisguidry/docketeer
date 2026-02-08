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
| `read_skill_file` | Read any file from a skill directory |
| `install_skill` | Install a skill from a git repository |
| `uninstall_skill` | Remove an installed skill |

## How it works

Skills live in `{workspace}/skills/`. The plugin provides three levels of
progressive disclosure:

1. **System prompt** — skill names and descriptions are always available
2. **activate_skill** — loads the full SKILL.md body on demand
3. **read_skill_file** — reads any file from the skill directory on demand

## Configuration

No configuration required. Skills are discovered automatically from the
`skills/` directory in the agent's workspace.
