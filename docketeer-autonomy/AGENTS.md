# docketeer-autonomy

The autonomous inner life plugin. Everything that makes a docketeer agent
feel like a personality rather than a plain chatbot lives here.

## Structure

- **`cycles.py`** — reverie and consolidation task functions. Reverie runs
  periodically, consolidation runs on a cron schedule. Both read guidance
  from PRACTICE.md sections.
- **`digest.py`** — builds conversation digests from recent chat activity,
  injected into reverie for awareness of what happened across rooms.
- **`people.py`** — loads per-user profile and recent journal mentions.
- **`rooms.py`** — loads per-room notes and recent journal mentions.
- **`journal.py`** — journal_add and journal_entries tools, registered via
  the tool registry.
- **`prompt.py`** — prompt provider that reads SOUL.md + PRACTICE.md +
  BOOTSTRAP.md and returns them as SystemBlocks.
- **`context.py`** — ContextProvider implementation that injects people
  profiles and room notes into conversation context.
- **`soul.md`**, **`practice.md`**, **`bootstrap.md`** — default templates
  copied to the workspace on first run.

## Testing

Tests mirror the source structure. The conftest provides the same workspace
and tool_context fixtures as core. Tests for cycles use a real Brain with
a fake Anthropic backend (same pattern as core brain tests).
