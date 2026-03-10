# docketeer-slack

Slack chat backend for [Docketeer](https://pypi.org/project/docketeer/).

This plugin connects Docketeer to Slack using:

- **Socket Mode** for inbound events
- **Slack Web API** for outbound actions and history

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DOCKETEER_SLACK_BOT_TOKEN` | _(required)_ | Slack bot token (`xoxb-...`) |
| `DOCKETEER_SLACK_APP_TOKEN` | _(required)_ | Slack app token for Socket Mode (`xapp-...`) |
| `DOCKETEER_SLACK_CHANNELS` | _(optional)_ | Comma-separated allowlist of channel IDs |
| `DOCKETEER_SLACK_BOT_NAME` | `slackbot` | Fallback username if auth lookup does not return one |

## Required Slack app setup

- Enable **Socket Mode**
- Create an app-level token with `connections:write`
- Install the app to your workspace
- Subscribe to events:
  - `app_mention`
  - `message.im`
  - `message.mpim`

Recommended bot scopes:

- `app_mentions:read`
- `chat:write`
- `reactions:write`
- `channels:history`
- `groups:history`
- `im:history`
- `mpim:history`
- `channels:read`
- `groups:read`
- `im:read`
- `mpim:read`
- `files:write`
