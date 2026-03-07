# docketeer-tui

Terminal chat backend for [Docketeer](https://pypi.org/project/docketeer/).
Talk to your agent directly in the terminal — no Rocket.Chat, no browser, no
signup. Ideal for local development and trying things out.

Install `docketeer-tui` alongside `docketeer` and it will be automatically
discovered as the chat backend. Also contributes TUI-specific context to the
system prompt via the `docketeer.prompt` entry point.

## Configuration

No configuration required. If both `docketeer-tui` and another chat backend
are installed, set:

```sh
export DOCKETEER_CHAT=tui
```
