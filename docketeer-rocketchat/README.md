# docketeer-rocketchat

[Rocket Chat](https://www.rocket.chat/) chat backend for
[Docketeer](../README.md). Connects to Rocket Chat via DDP (WebSocket) for
real-time message subscriptions and the REST API for sending messages, uploading
files, and managing presence.

## Setup

You'll need a Rocket Chat server with a bot account. Add these to your
`.envrc.private`:

```sh
export DOCKETEER_ROCKETCHAT_URL="https://your-rocketchat-server.example.com"
export DOCKETEER_ROCKETCHAT_USERNAME="your-bot-username"
export DOCKETEER_ROCKETCHAT_PASSWORD="your-bot-password"
```

## Environment variables

| Variable                         | Default      | Description            |
|----------------------------------|--------------|------------------------|
| `DOCKETEER_ROCKETCHAT_URL`       | _(required)_ | Rocket Chat server URL |
| `DOCKETEER_ROCKETCHAT_USERNAME`  | _(required)_ | Bot account username   |
| `DOCKETEER_ROCKETCHAT_PASSWORD`  | _(required)_ | Bot account password   |
