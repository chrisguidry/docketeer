# Docketeer

Build the AI personal assistant you need with
[Anthropic](https://platform.claude.com/docs/en/api/sdks/python) and
[Docket](https://github.com/chrisguidry/docket).

## What is docketeer?

Docketeer is a _toolkit_ for building the autonomous AI agent you want without
bringing in dozens or hundreds of modules you don't. Instead of a huge and
sprawling monolithic system, Docketeer is small, opinionated, and designed to be
extended through plugins.

The core of Docketeer is an agent loop based on Anthropic's client SDK, a Docket
for scheduling autonomous work, and a small set of tools for managing memory in
its workspace. Any other functionality can be added through simple Python
plugins that register via standard Python
[entry points](https://packaging.python.org/en/latest/specifications/entry-points/).
Bring a plugin to connect to your favorite messaging
service (Docketeer is developed against Rocket Chat, but plugins can be easily
developed for other services as well).

Docketeer is currently under heavy early and active development. If you're
feeling adventurous, please jump in and send PRs! Otherwise, follow along until
things are a little more baked.

## The philosophy behind Docketeer's autonomy

Our frontier models don't need much help at all to behave autonomously — they
just need an execution model to support it. All we're doing here is giving the
agent a Docket of its own, on which it can schedule its own future work. As of
today, the agent can use a tool to schedule a `nudge` Docket task to prompt
itself at any future time.

Additionally, two built-in `Perpetual` Docket tasks `reverie` and
`consolidation` give the agent recurring opportunities throughout the day to
evaluate the world, reflect on what's been going on recently, schedule new
tasks, and to update its own memory and knowledge base.

Most importantly, the agent can direct itself by updating markdown files in its
own workspace for those prompts. This self-prompting and the ability to
self-improve its prompts are the heart of Docketeer's autonomy.

## Standards

Yes, Docketeer is developed entirely with AI coding tools. Yes, every line of
Docketeer has been reviewed by me, the author. Yes, 100% test coverage is
required and enforced.

## Security

Obviously, there are inherent risks to running an autonomous agent. Docketeer
does not attempt to mitigate those risks. By using only Anthropic's extremely
well-aligned and intelligent models, I'm hoping to avoid the most catastrophic
outcomes that could come from letting an agent loose on your network. However,
the largest risks are still likely to come from nefarious _human_ actors who are
eager to target these new types of autonomous AIs.

Docketeer's architecture _does not require listening to the network at all_.
There is no web interface and no API. Docketeer starts up, connects to Redis,
connects to the chat system, and _only_ responds to prompts that come from you
and the people you've allowed to interact with it via chat or from itself via
future scheduled tasks.

Prompt injection will remain a risk with any agent that can reach out to the
internet for information.

## Project layout

Docketeer is a [uv workspace](https://docs.astral.sh/uv/concepts/workspaces/).
The `docketeer/` package is the core agent engine. Everything else is a plugin —
currently `docketeer-rocketchat` (chat backend) and `docketeer-web` (search and
HTTP tools).

Chat backends and tool plugins are discovered at runtime through Python
[entry points](https://packaging.python.org/en/latest/specifications/entry-points/).
The core package doesn't know which plugins are installed — it just finds and
loads whatever's there.

## Running docketeer

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker (for Redis)
- An [Anthropic API key](https://console.anthropic.com/)
- [direnv](https://direnv.net/) (optional, for automatic environment variable loading)

### Install

```sh
git clone https://github.com/chrisguidry/docketeer.git
cd docketeer
uv sync
```

This installs all workspace packages and dev dependencies into a local `.venv`.

### Start Redis

Docketeer uses Redis (via [Docket](https://github.com/chrisguidry/docket)) to
schedule future tasks like reminders and periodic thinking cycles.

```sh
docker compose up -d
```

This starts Redis on `localhost:6379`, which is the default Docketeer expects.

### Set environment variables

Create a `.envrc.private` file (gitignored) with your credentials:

```sh
export DOCKETEER_ANTHROPIC_API_KEY="sk-ant-..."
```

If you use [direnv](https://direnv.net/), the `.envrc` will automatically source
`.envrc.private` when you enter the directory. Otherwise, `source .envrc.private`
yourself.

The core environment variables are:

| Variable                       | Default                    | Description                                      |
| ------------------------------ | -------------------------- | ------------------------------------------------ |
| `DOCKETEER_ANTHROPIC_API_KEY`  | _(required)_               | Your Anthropic API key                           |
| `DOCKETEER_CLAUDE_MODEL`       | `claude-opus-4-6`          | Which Claude model to use                        |
| `DOCKETEER_DATA_DIR`           | `~/.docketeer`             | Where the agent stores its memory and audit logs |
| `DOCKETEER_DOCKET_URL`         | `redis://localhost:6379/0` | Redis connection for task scheduling             |
| `DOCKETEER_DOCKET_NAME`        | `docketeer`                | Name of the Docket instance                      |
| `DOCKETEER_REVERIE_INTERVAL`   | `PT30M` (30 min)           | Background thinking cycle interval               |
| `DOCKETEER_CONSOLIDATION_CRON` | `0 3 * * *`                | Cron schedule for daily memory consolidation     |

Each plugin has its own environment variables — see
[docketeer-rocketchat](docketeer-rocketchat/README.md) and
[docketeer-web](docketeer-web/README.md).

### Start the agent

```sh
docketeer start
```

Or in dev mode (auto-reloads on code changes):

```sh
docketeer start --dev
```

The agent will connect to your Rocket Chat server, load conversation history from
its DM rooms, and start responding to messages.

### Running tests

```sh
uv run pytest
```

This runs tests across all packages with 100% branch coverage enforced.

### Writing a plugin

Docketeer discovers plugins through two entry point groups:

- **`docketeer.chat`** — chat backends (how the agent talks to people)
- **`docketeer.tools`** — tool plugins (what the agent can do)

Look at `docketeer-rocketchat` and `docketeer-web` for working examples. Each is
a small, self-contained Python package that registers itself through its
`pyproject.toml` entry points.
