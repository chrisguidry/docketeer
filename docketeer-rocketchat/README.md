# docketeer-rocketchat

[Rocket Chat](https://www.rocket.chat/) chat backend for
[Docketeer](https://pypi.org/project/docketeer/). Connects to a Rocket Chat
server via DDP (WebSocket) for real-time message subscriptions and the REST API
for sending messages, uploading files, and managing presence.

Install `docketeer-rocketchat` alongside `docketeer` and it will be
automatically discovered as the chat backend.

## Tools

- **`send_file`** — send a file from the agent's workspace to the current chat room

## Configuration

| Variable                         | Default      | Description            |
|----------------------------------|--------------|------------------------|
| `DOCKETEER_ROCKETCHAT_URL`       | _(required)_ | Rocket Chat server URL |
| `DOCKETEER_ROCKETCHAT_USERNAME`  | _(required)_ | Bot account username   |
| `DOCKETEER_ROCKETCHAT_PASSWORD`  | _(required)_ | Bot account password   |
