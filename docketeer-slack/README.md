# docketeer-slack

Slack chat backend for [Docketeer](https://pypi.org/project/docketeer/).

This plugin connects Docketeer to Slack using:

- **Socket Mode** for inbound events
- **Slack Web API** for outbound actions and history

## Creating a Slack app

Go to [api.slack.com/apps](https://api.slack.com/apps) and click
**Create New App** → **From scratch**. Give it a name and select your
workspace.

### 1. Enable Socket Mode

In the left sidebar, go to **Socket Mode** and toggle it on. Slack will
prompt you to create an app-level token — name it anything (e.g. "socket")
and give it the `connections:write` scope. Copy the `xapp-...` token that's
generated; this is your `DOCKETEER_SLACK_APP_TOKEN`.

### 2. Add bot token scopes

In the left sidebar, go to **OAuth & Permissions** and scroll down to
**Bot Token Scopes**. Add all of the following:

| Scope | What it's for |
|---|---|
| `app_mentions:read` | Receive @mentions in channels |
| `chat:write` | Send messages and stream replies |
| `reactions:read` | Receive emoji reaction events |
| `reactions:write` | Add/remove emoji reactions on messages |
| `channels:history` | Read channel message history |
| `groups:history` | Read private channel history |
| `im:history` | Read DM history |
| `mpim:history` | Read group DM history |
| `channels:read` | List channels the bot is in |
| `groups:read` | List private channels |
| `im:read` | List DM conversations |
| `mpim:read` | List group DM conversations |
| `files:write` | Upload files |

### 3. Subscribe to events

In the left sidebar, go to **Event Subscriptions** and toggle the feature
on. Under **Subscribe to bot events**, add:

- `app_mention`
- `message.im`
- `message.mpim`
- `reaction_added`

### 4. Enable the Messages tab

In the left sidebar, go to **App Home**. Under **Messages Tab**, toggle
it on and check **Allow users to send Slash commands and messages from the
messages tab**. Without this, users won't be able to DM the bot.

### 5. Install the app to your workspace

In the left sidebar, go to **Install App** and click **Install to
Workspace**. Authorize the permissions when prompted. Copy the
`xoxb-...` bot token that appears; this is your
`DOCKETEER_SLACK_BOT_TOKEN`.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DOCKETEER_SLACK_BOT_TOKEN` | _(required)_ | Bot token from step 5 (`xoxb-...`) |
| `DOCKETEER_SLACK_APP_TOKEN` | _(required)_ | App-level token from step 1 (`xapp-...`) |
| `DOCKETEER_SLACK_CHANNELS` | _(optional)_ | Comma-separated allowlist of channel IDs |
| `DOCKETEER_SLACK_BOT_NAME` | `slackbot` | Fallback username if auth lookup does not return one |

## Talking to the bot

- **DMs**: Just open a direct message with the bot and start typing.
- **Channels**: Either `@mention` the bot in a message, or add the channel
  ID to `DOCKETEER_SLACK_CHANNELS` to have the bot listen to all messages
  in that channel.
- **Reactions**: Emoji reactions you leave on the bot's messages are
  forwarded to the agent, so it can use them as signals (e.g. approvals).
