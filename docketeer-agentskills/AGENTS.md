# docketeer-agentskills

[Agent Skills](https://agentskills.io/specification) plugin. Registers both
`docketeer.tools` (for installing/managing skills) and `docketeer.prompt`
(for injecting the skill catalog into the system prompt).

## Structure

- **`discovery.py`** — finds and parses skill YAML files in the workspace.
- **`tools.py`** — tool functions for installing, listing, and removing skills.
- **`prompt.py`** — prompt provider that builds the skill catalog block.

## Testing

The `conftest.py` provides a workspace fixture pre-populated with sample skill
files. Tests verify skill discovery, tool behavior, and prompt generation
against that fixture data.
