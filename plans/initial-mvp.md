# Docketeer: Lightweight Agentic System

A headless agent using Claude for reasoning, pydocket for temporal awareness, and Rocket Chat for communication.

## Philosophy

- Small, forkable, personal — not a product
- Opinionated: Claude + Docket + Rocket Chat specifically
- Explainable: markdown memories, visible task queue
- Multi-user aware from day one
- The LLM decides how to organize its memory — code provides tools but
  doesn't dictate structure (the journal and profile contracts are the
  exceptions, and they're tool-mediated)

## Architecture Overview

```
                    Rocket Chat Server
                           ↑
                     (websocket)
                           │
              ┌────────────┴────────────┐
              │     Docketeer Agent     │
              │                         │
              │   chat.py (realtime)    │──> presence, messages
              │          │              │
              │          v              │
              │      brain.py           │──> Claude reasoning + tools
              │          │              │
              │    ┌─────┴─────┐        │
              │    │           │        │
              │    v           v        │
              │ memory/     docket      │
              └─────────────────────────┘
                           │
                      (Redis)
                           │
                    Docket Worker
                    (executes tasks)
```

**No web ingress** — Agent connects outbound to Rocket Chat.

**Hybrid approach:**
- **Minimal DDP client** (~100 lines) for real-time message subscriptions via websocket
- **Async REST API** (httpx) for sending messages, presence, actions

## Current File Structure

```
docketeer/
├── pyproject.toml
├── plans/
│   └── initial-mvp.md      # This file
├── src/docketeer/
│   ├── __init__.py
│   ├── __main__.py
│   ├── main.py              # Entry: chat client + message loop
│   ├── config.py            # Settings from environment
│   ├── brain.py             # Claude reasoning loop with tools + auto-context
│   ├── tools.py             # Tool registry + all tool definitions
│   ├── ddp.py               # Minimal DDP client for subscriptions
│   ├── chat.py              # Rocket Chat client (DDP + async REST)
│   ├── soul.md              # System prompt template (new installs)
│   └── bootstrap.md         # First-run guidance (deleted by agent when done)
└── ~/.docketeer/            # Data directory (DOCKETEER_DATA_DIR)
    ├── memory/              # Agent's workspace
    │   ├── SOUL.md          # Live system prompt (diverges from template)
    │   ├── people/{name}/
    │   │   └── profile.md   # Auto-loaded per-person context
    │   ├── notes/
    │   └── journal/
    │       └── YYYY-MM-DD.md
    └── audit/
        └── YYYY-MM-DD.jsonl # Tool call audit log
```

## What's Built

### Phase 1: Foundation ✅
- **config.py** — Dataclass from env vars (`DOCKETEER_*` prefix)
- **ddp.py** — Minimal DDP/websocket client
- **chat.py** — Hybrid RC client (DDP subscriptions + async httpx REST)

### Phase 2: Agent Core ✅
- **brain.py** — Claude reasoning with agentic tool loop (up to 10 rounds),
  streaming responses, prompt caching (3 cache breakpoints: SOUL.md, last
  tool def, latest tool result), context compaction via Haiku summarization
  when approaching 140k tokens
- **tools.py** — Decorator-based registry with auto schema derivation from
  type hints. Workspace tools (list/read/write/search/delete files), journal
  tools (add/read/search), web tools (search via Brave, HTTP requests,
  download)
- **main.py** — Message loop, history loading, dev mode with watchfiles

### Phase 3: Memory & Identity ✅
Instead of a separate `memory.py`, memory is handled through:
- **Journal tools** — `journal_add`, `journal_read`, `journal_search` enforce
  the `journal/YYYY-MM-DD.md` format. Append-only, agent never writes directly.
- **Workspace file tools** — Agent manages `people/`, `notes/`, and any other
  files it wants through `read_file`, `write_file`, `search_files`
- **Auto-context loading** — `brain.py` scans `people/*/profile.md` at startup
  for `**Username:** @handle` lines, builds a username→person mapping. On each
  message, auto-loads the speaker's profile + last 7 days of journal mentions
  as a dynamic system block. Map rebuilds when agent writes to `people/`.
- **SOUL.md** — Expanded system prompt (~100 lines) covering identity,
  personality, social intelligence, privacy rules, journaling habits (tags,
  wikilinks, reflection triggers), and workspace conventions
- **Timestamped messages** — All messages (history + real-time) include
  `[YYYY-MM-DD HH:MM]` timestamps in local time so the agent has temporal
  awareness across the whole conversation
- **Presence indicators** — Goes "away" while thinking, back to "online" when done
- **Audit log** — Tool calls logged to `audit/YYYY-MM-DD.jsonl` (outside the
  agent's workspace so it can't see or tamper with its own audit trail)
- **Instance lock** — flock-based so only one docketeer runs at a time

### Phase 4: Scheduling 🔜
- **tasks.py** — Built-in docket tasks (remind, check-in, daily summary)
- Scheduling tools (schedule_task, cancel_task, list_scheduled)
- Wire docket worker into main.py

### Future
- Group room support (auto-load profiles for multiple speakers)
- Tool call visibility as RC attachments (green/red color coding)
- Topic-based context pre-loading
- Dynamic script loading with safety checks

## Key Design Decisions

### Memory Architecture

Three tiers, modeled after human memory:

1. **Working memory (always loaded):** SOUL.md — identity, personality, social
   rules, journaling habits. Cached via prompt caching. ~2,200 tokens.

2. **Episodic context (loaded per-conversation):** Person profile + recent
   journal mentions, auto-loaded when someone messages. Non-cached but saves
   the tool calls the agent would otherwise make. ~500–2,000 tokens.

3. **Long-term memory (searchable):** Full journal history, all notes, older
   observations. Accessed through journal_search, search_files, read_file.
   Agent decides when to dig deeper.

Information flows upward through distillation: journal (raw stream) →
people files (current understanding) → SOUL.md (core principles).

### Agent Autonomy

The agent decides how to organize its workspace. Code provides two contracts:

1. **Journal** — `journal/YYYY-MM-DD.md` with `- HH:MM | text` entries,
   managed exclusively through journal tools
2. **Profiles** — `people/{name}/profile.md` with a `**Username:** @handle`
   line, auto-loaded by brain.py

Everything else — what goes in the profile, how to organize notes, when to
reflect, what to journal — is guidance in SOUL.md, not code.

### Message Flow
```
1. DDP subscription receives message event (with timestamp)
2. Parse to IncomingMessage
3. Set presence to "away"
4. Fetch any image attachments
5. Auto-load speaker's profile + recent journal mentions
6. Build system prompt (SOUL.md cached + dynamic person context)
7. Claude processes with tools (agentic loop, up to 10 rounds)
8. Tool calls execute, audit-logged
9. Send response to room
10. Set presence back to "online"
```

## Dependencies

```toml
dependencies = [
    "pydocket",
    "anthropic",
    "websockets",
    "pyyaml",
    "watchfiles",
    "httpx",
]
```

No web framework needed — purely outbound connections.

## Reference Files

- `/home/chris/src/github.com/chrisguidry/docket/src/docket/docket.py` — Docket API (add, cancel, snapshot)
- `/home/chris/src/github.com/chrisguidry/docket/src/docket/dependencies/_perpetual.py` — Perpetual task pattern
