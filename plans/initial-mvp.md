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
              │ memory/     docket      │
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
│   └── chat.py          # Rocket Chat client (DDP + REST)
└── workspace/           # Writeable area (gitignored)
    ├── memory/
    │   ├── users/{user_id}/
    │   │   ├── profile.md    # Timestamped notes about this user
    │   │   └── history.md    # Time-anchored conversation log
    │   └── notes/
    │       └── {topic}.md    # Freeform markdown notes
    └── scripts/              # Future: agent-created tasks
```

## Core Components

### 1. config.py (~40 lines)
Dataclass loading from environment:
- `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` (default: `claude-opus-4-6`)
- `REDIS_URL`, `DOCKET_NAME`
- `ROCKETCHAT_URL` (websocket: `wss://server/websocket`)
- `ROCKETCHAT_USERNAME`, `ROCKETCHAT_PASSWORD` (or token-based auth)
- `WORKSPACE_PATH`

### 2. chat.py (~200 lines)
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

**chat.py - High-level wrapper:**
- `RocketClient.connect()` - DDP connect + REST auth
- `RocketClient.send_message(room_id, text, attachments)` - Via REST API
- `RocketClient.send_typing(room_id)` - Via DDP method
- `async for msg in client.incoming_messages()` - From DDP subscription
- `RocketClient.fetch_attachment(url)` - Download attachment bytes
- `RocketClient.fetch_room_history(room_id)` - Load older messages
- `RocketClient.list_dm_rooms()` - List DM rooms

Uses `rocketchat-API` (maintained) for REST calls, own code for DDP subscriptions.

`IncomingMessage` dataclass: `user_id`, `username`, `display_name`, `text`, `room_id`, `is_direct`, `attachments`

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

### 4. tools.py (~200 lines)
Claude tool definitions and execution via `anthropic` SDK tool_use.

**Workspace Tools:**
| Tool | Purpose |
|------|---------|
| `list_files` | List files/dirs in workspace |
| `read_file` | Read a text file |
| `write_file` | Write a text file |

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

**Rocket Chat Tools:**
| Tool | Purpose |
|------|---------|
| `send_message` | Send to user (@username) or room |

Tool calls are surfaced to users as collapsed Rocket Chat attachments with
color coding (green for success, red for errors).

### 5. brain.py (~150 lines)
Claude reasoning loop using `anthropic` SDK with tool_use:
1. Load user context from memory
2. Build system prompt with context + current time
3. Log incoming message to history
4. Agentic loop: Claude → tool calls → results → Claude (up to 10 rounds)
5. Return `BrainResponse` with text + list of `ToolCall` records
6. Caller sends response and logs to history

Returns `BrainResponse(text, tool_calls)` so main.py can format tool calls
as Rocket Chat attachments.

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

### 7. main.py (~150 lines)
Entry point running two concurrent async loops:
1. Load config, create ToolExecutor, RocketClient, Brain
2. Start Docket context manager
3. Register built-in tasks
4. Start Worker in background (`worker.run_forever()`)
5. Connect to Rocket Chat
6. Load conversation history for existing DM rooms
7. Message loop: `async for msg in client.incoming_messages()`
   - Show typing indicator
   - Build content (fetch images if attached)
   - Process with Brain
   - Send response with tool call attachments
8. Graceful shutdown: disconnect

Dev mode: `docketeer --dev` uses watchfiles for live reload.

No web server - purely outbound connections to Rocket Chat and Redis.

## Key Design Decisions

### Message Flow
```
1. Websocket subscription receives message event
2. Parse to IncomingMessage (user_id, username, text, room_id, attachments)
3. Send typing indicator to room
4. Fetch any image attachments
5. Build system prompt with user context + current time
6. Claude processes with tools available (agentic loop, up to 10 rounds)
7. Tool calls execute against workspace/memory/docket/chat
8. Send response to same room with tool call attachments
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

### Tool Visibility
Tool calls are surfaced as Rocket Chat message attachments:
- Green (#28a745) for successful calls
- Red (#dc3545) for errors
- Collapsed by default so they don't clutter the chat
- Title shows tool name and arguments
- Body shows result (truncated to 200 chars)

## Dependencies

```toml
[project]
dependencies = [
    "pydocket",
    "anthropic",
    "rocketchat-API",    # REST API wrapper (maintained)
    "websockets",        # For our minimal DDP client
    "pyyaml",
    "watchfiles",        # Dev mode live reload
]
```

No web framework needed - agent is a pure client.

## Implementation Order

### Phase 1: Foundation ✅
1. **pyproject.toml** - Project setup
2. **config.py** - Settings from environment
3. **ddp.py** - Minimal DDP client
4. **chat.py** - Rocket Chat wrapper (DDP + REST)

### Phase 2: Agent Core ✅
5. **brain.py** - Claude reasoning loop with tool_use agentic loop
6. **tools.py** - Workspace file tools (list_files, read_file, write_file)
7. **main.py** - Wire it all together with tool call attachments

### Phase 3: Memory
8. **memory.py** - Markdown memory system
9. Add memory tools to tools.py (recall, remember, note_about_user)
10. Wire memory into brain.py system prompt

### Phase 4: Scheduling
11. **tasks.py** - Built-in docket tasks (remind, check-in)
12. Add scheduling tools to tools.py (schedule_task, cancel_task, list_scheduled)
13. Wire docket worker into main.py

### Phase 5: Polish
14. More tools (send_message, etc.)
15. Integration tests with in-memory docket

### Future (post-MVP)
- **loader.py** - Dynamic script loading with AST safety checks
- Script sandboxing (allowlist imports, blocklist patterns)
- Agent-created Python tasks saved to workspace/scripts/

## Verification

1. **Unit tests**: memory.py parsing, tasks.py time parsing
2. **Integration test**: Full message flow with mocked Rocket Chat + in-memory docket
3. **Manual test**:
   - Start with `docketeer --dev`
   - Agent should connect and load history
   - Send DM to bot, verify typing indicator and response
   - Ask bot to write/read files in workspace
   - Schedule a reminder, wait for it

## Reference Files

- `/home/chris/src/github.com/chrisguidry/docket/src/docket/docket.py` - Docket API (add, cancel, snapshot)
- `/home/chris/src/github.com/chrisguidry/docket/src/docket/dependencies/_perpetual.py` - Perpetual task pattern
