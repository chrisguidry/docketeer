# docketeer-autonomy

Autonomous inner life plugin for [Docketeer](https://github.com/chrisguidry/docketeer).
Adds reverie/consolidation cycles, journaling, people profiles, room context,
and the default personality templates (SOUL.md, PRACTICE.md, BOOTSTRAP.md).

Install this plugin for the full "inner life" experience. Leave it out for a
plain chatbot that just responds to messages.

## Features

- **Reverie** — periodic background processing cycle for checking promises,
  noticing what needs attention, and tending to the workspace
- **Consolidation** — daily memory integration cycle for reviewing experience
  and updating knowledge
- **Journal** — timestamped daily entries with wikilinks and hashtags
- **People profiles** — per-user context files loaded automatically on first
  message from each user
- **Room context** — per-room notes loaded on first message in each room
- **System prompt templates** — SOUL.md (personality), PRACTICE.md (habits),
  BOOTSTRAP.md (first-run setup)

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DOCKETEER_REVERIE_MODEL` | `balanced` | Model tier for reverie cycle |
| `DOCKETEER_CONSOLIDATION_MODEL` | `balanced` | Model tier for consolidation |
| `DOCKETEER_REVERIE_INTERVAL` | `PT30M` | How often reverie runs |
| `DOCKETEER_CONSOLIDATION_CRON` | `0 3 * * *` | Cron schedule for consolidation |
| `DOCKETEER_REVERIE_ROOM_CHAR_LIMIT` | `4000` | Max chars per room before summarization in digest |

## Entry points

| Group | Name | Target |
|-------|------|--------|
| `docketeer.tools` | `autonomy` | Journal tools (journal_add, journal_entries) |
| `docketeer.prompt` | `autonomy` | System prompt from SOUL.md + PRACTICE.md + BOOTSTRAP.md |
| `docketeer.tasks` | `autonomy` | Reverie and consolidation task collections |
| `docketeer.context` | `autonomy` | People profile and room context injection |
