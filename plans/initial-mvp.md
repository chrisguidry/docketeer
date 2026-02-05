# Docketeer: Lightweight Agentic System

A headless agent using Claude for reasoning, pydocket for temporal awareness, and Rocket Chat for communication.

## Philosophy (via nanoclaw)

- Small, forkable, personal - not a product
- Opinionated: Claude + Docket + Rocket Chat specifically
- Explainable: markdown memories, visible task queue
- Multi-user aware from day one

## Architecture Overview

```
                    Rocket Chat Server
                           ↑
                     (websocket)
                           │
              ┌────────────┴────────────┐
              │     Docketeer Agent     │
              │                         │
              │   chat.py (realtime)    │──> presence, typing, messages
              │          │              │
              │          v              │
              │      brain.py           │──> Claude reasoning + tools
              │          │              │
              │    ┌─────┴─────┐        │
              │    │           │        │
              │    v           v        │
              │ memory/    scripts/     │
              └─────────────────────────┘
                           │
                      (Redis)
                           │
                    Docket Worker
                    (executes tasks)
```

**No web ingress** - Agent connects outbound to Rocket Chat.

**Hybrid approach:**
- **Minimal DDP client** (~100 lines) for real-time message subscriptions via websocket
- **REST API** (via `rocketchat-API` library) for sending messages, presence, actions

**What is DDP?** Distributed Data Protocol - the websocket protocol Meteor uses.
Rocket Chat is built on Meteor, so this is THE way clients communicate.
The official `@rocket.chat/ddp-client` npm package uses the same protocol.

The protocol is simple (this is what we implement):
```
1. Connect websocket to wss://server/websocket
2. Send: {"msg": "connect", "version": "1", "support": ["1"]}
3. Receive: {"msg": "connected", "session": "..."}
4. Subscribe: {"msg": "sub", "id": "1", "name": "stream-room-messages", "params": [room_id, false]}
5. Receive: {"msg": "changed", "collection": "...", "fields": {message data}}
6. Keepalive: respond {"msg": "pong"} to {"msg": "ping"}
```

## File Structure

```
docketeer/
├── pyproject.toml
├── src/docketeer/
│   ├── __init__.py
│   ├── main.py          # Entry: runs chat client + docket worker
│   ├── config.py        # Settings from environment
│   ├── brain.py         # Claude reasoning loop with tools
│   ├── tools.py         # Tool definitions for Claude
│   ├── memory.py        # Markdown memory read/write
│   ├── tasks.py         # Built-in docket tasks
│   ├── ddp.py           # Minimal DDP client for subscriptions
│   ├── chat.py          # Rocket Chat client (DDP + REST)
│   └── loader.py        # Dynamic script loading with safety checks
└── workspace/           # Writeable area (gitignored)
    ├── memory/
    │   ├── users/{user_id}/
    │   │   ├── profile.md    # Timestamped notes about this user
    │   │   └── history.md    # Time-anchored conversation log
    │   └── notes/
    │       └── {topic}.md    # Freeform markdown notes
    └── scripts/
        └── {task_name}.py    # Agent-created tasks
```

## Core Components

### 1. config.py (~40 lines)
Dataclass loading from environment:
- `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`
- `REDIS_URL`, `DOCKET_NAME`
- `ROCKETCHAT_URL` (websocket: `wss://server/websocket`)
- `ROCKETCHAT_USERNAME`, `ROCKETCHAT_PASSWORD` (or token-based auth)
- `WORKSPACE_PATH`

### 2. chat.py (~150 lines)
Hybrid Rocket Chat client: minimal DDP for subscriptions + REST for actions.

**ddp.py (~100 lines) - Minimal DDP client using `websockets` library:**
```python
class DDPClient:
    async def connect(url: str) -> None        # wss://server/websocket
    async def call(method: str, params: list) -> dict  # RPC method call
    async def subscribe(name: str, params: list) -> str  # Returns sub ID
    async def unsubscribe(sub_id: str) -> None
    async def events() -> AsyncIterator[dict]  # Yields subscription events

# Internal: background task handles ping/pong keepalive
```

The client wraps raw websocket messages into the DDP format and handles the
connection lifecycle. Subscription events are yielded as they arrive.

**chat.py (~50 lines) - High-level wrapper:**
- `RocketClient.connect()` - DDP connect + REST auth
- `RocketClient.send_message(room_id, text)` - Via REST API
- `RocketClient.set_presence(status)` - Via REST API
- `RocketClient.send_typing(room_id)` - Via REST API (or DDP method)
- `async for msg in client.incoming_messages()` - From DDP subscription

Uses `rocketchat-API` (maintained) for REST calls, own code for DDP subscriptions.

`IncomingMessage` dataclass: `user_id`, `username`, `display_name`, `text`, `room_id`, `is_direct`

### 3. memory.py (~120 lines)
Markdown-based memory with timecoded logs:
- `get_user_context(user_id)` - Load profile + recent history
- `append_to_profile(user_id, note)` - Add a timestamped note about user
- `append_history(user_id, role, content)` - Time-anchored conversation log
- `recall(query)` - Search all markdown files by keyword
- `remember(name, content)` - Create/update a general note

Simple journal approach - no rigid structure:
```markdown
# chris

- 2026-02-05T0930 | Prefers morning reminders
- 2026-02-05T1420 | Working on docketeer project
- 2026-02-12T1100 | Mentioned upcoming trip to Portland
```

Notes are freeform markdown files:
```markdown
# docketeer project

Chris's lightweight agent system using pydocket.

- 2026-02-05T1430 | Started planning
- 2026-02-06T0900 | Decided on Rocket Chat for comms
```

Timestamps use ISO8601 format (`YYYY-MM-DDTHHMM`) - real dates, not relative.

### 4. tools.py (~150 lines)
Claude tool definitions and execution:

**Memory Tools:**
| Tool | Purpose |
|------|---------|
| `recall` | Search memory files by keyword |
| `remember` | Create/append to a markdown note |
| `note_about_user` | Add timestamped note to user's profile |

**Scheduling Tools:**
| Tool | Purpose |
|------|---------|
| `schedule_task` | Schedule work for later |
| `cancel_task` | Cancel by key |
| `list_scheduled` | Show pending tasks via `docket.snapshot()` |
| `create_script` | Write new Python task (sandboxed) |

**Rocket Chat Tools:**
| Tool | Purpose |
|------|---------|
| `send_message` | Send to user (@username) or room |
| `fetch_history` | Load older messages from current or specified room |
| `fetch_attachment` | Download an attachment by URL (for re-examining images) |
| `list_rooms` | List rooms the agent has access to |
| `search_messages` | Search messages across rooms by keyword |

The Rocket Chat toolset gives the agent agency over its communication channel -
it can proactively look up context, re-examine attachments, and navigate the
chat history beyond what's automatically loaded.

### 5. brain.py (~120 lines)
Claude reasoning loop:
1. Load user context from memory
2. Build system prompt with context + current time
3. Log incoming message to history
4. Agentic loop: Claude → tool calls → results → Claude
5. Send final response, log to history

System prompt emphasizes:
- Multi-user awareness (always check WHO is talking)
- Temporal thinking (schedule follow-ups, don't just respond and forget)
- Incremental learning (update profiles as you learn)

### 6. tasks.py (~100 lines)
Built-in docket tasks:
- `remind_user(user_id, message)` - Send reminder via DM
- `check_in_user(user_id, topic)` - Proactive follow-up
- `summarize_day()` - Perpetual daily task (automatic=True)

Helper: `parse_when(str)` - Parse "in 1 hour", "tomorrow 9am", ISO format

### 7. loader.py (~80 lines)
Dynamic script loading with safety:
- AST validation: only allowed imports (datetime, json, re, pathlib, typing)
- Pattern blocklist: no os, subprocess, eval, exec, open
- Scripts must define `async def run(ctx: TaskContext)`
- Save to `workspace/scripts/{name}.py`
- Load via `importlib.util`

### 8. main.py (~100 lines)
Entry point running two concurrent async loops:
1. Load config, create Memory, RocketClient, Brain
2. Start Docket context manager
3. Register built-in tasks
4. Start Worker in background (`worker.run_forever()`)
5. Connect to Rocket Chat, set presence to "online"
6. Message loop: `async for msg in client.messages()`
   - Show typing indicator
   - Process with Brain
   - Send response
7. Graceful shutdown: set presence "away", disconnect

No web server - purely outbound connections to Rocket Chat and Redis.

## Key Design Decisions

### Message Flow
```
1. Websocket subscription receives message event
2. Parse to IncomingMessage (user_id, username, text, room_id)
3. Send typing indicator to room
4. Load user's profile.md and recent history.md
5. Build system prompt with user context
6. Claude processes with tools available
7. Tool calls execute against memory/docket/chat
8. Send response to same room (typing stops automatically)
9. Conversation logged to user's history.md
```

### Multi-User Model
- Every message includes `user_id` from Rocket Chat
- User context loaded fresh each message
- Profile stores timestamped notes about each user
- Tasks include `user_id` in args for proper delivery
- No cross-user data leakage

### Self-Scheduling
The agent schedules itself via:
- Explicit: "remind me in 1 hour" → `schedule_task`
- Perpetual: Daily summary task with `automatic=True`
- Proactive: Agent notices deadline, offers to schedule check-in
- Learning from patterns: Notes in user profile inform future behavior

### Safety
- Script sandboxing: allowlist imports, blocklist patterns, AST validation
- Task limits via config: max runtime, max pending
- Docket's built-in Timeout dependency
- No network access in scripts (no requests, urllib)

## Dependencies

```toml
[project]
dependencies = [
    "pydocket",
    "anthropic",
    "rocketchat-API",    # REST API wrapper (maintained)
    "websockets",        # For our minimal DDP client
    "pyyaml",
]
```

No web framework needed - agent is a pure client.

## Implementation Order

### Phase 0: Documentation First
1. **plans/initial-mvp.md** - This plan as project documentation

### Phase 1: Foundation
2. **pyproject.toml** - Project setup
3. **config.py** - Settings foundation

### Phase 2: Rocket Chat Connection
4. **ddp.py** - Minimal DDP client (can test against RC directly)
5. **chat.py** - Rocket Chat wrapper (DDP + REST)

### Phase 3: Agent Core
6. **memory.py** - Markdown memory system
7. **tools.py** - Tool definitions (memory + scheduling)
8. **brain.py** - Claude reasoning loop with tool calling

### Phase 4: Rocket Chat Toolset
9. **chat_tools.py** - Rocket Chat tools for agent (fetch_history, fetch_attachment, etc.)
10. Wire chat tools into brain.py

### Phase 5: Scheduling
11. **tasks.py** - Built-in tasks
12. **loader.py** - Script validation/loading

### Phase 6: Integration
13. **main.py** - Wire it all together
14. **Tests** - Integration tests with in-memory docket

## Verification

1. **Unit tests**: memory.py parsing, loader.py validation, tasks.py time parsing
2. **Integration test**: Full message flow with mocked Rocket Chat + in-memory docket
3. **Manual test**:
   - Create bot user in Rocket Chat
   - Start with `python -m docketeer`
   - Agent should show as "online" in Rocket Chat
   - Send DM to bot, verify typing indicator and response
   - Schedule a reminder, wait for it
   - Create a script, schedule it

## Estimated Size

~900 lines of Python total (excluding tests)
- ddp.py: ~100 lines
- chat.py: ~50 lines
- memory.py: ~120 lines
- tools.py: ~150 lines
- brain.py: ~120 lines
- tasks.py: ~100 lines
- loader.py: ~80 lines
- config.py: ~40 lines
- main.py: ~100 lines

## Reference Files

- `/home/chris/src/github.com/chrisguidry/docket/src/docket/docket.py` - Docket API (add, cancel, snapshot)
- `/home/chris/src/github.com/chrisguidry/docket/src/docket/dependencies/_perpetual.py` - Perpetual task pattern
