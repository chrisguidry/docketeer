# docketeer-anthropic

Anthropic inference backend plugin for Docketeer.

This plugin provides two inference backends:

- **api**: Direct integration with the Anthropic API (default)
- **claude-code**: Uses the `claude -p` command via an executor

## Installation

```bash
pip install docketeer-anthropic
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DOCKETEER_ANTHROPIC_BACKEND` | `api` | Backend type: `api` or `claude-code` |
| `DOCKETEER_ANTHROPIC_API_KEY` | _(required for api)_ | Anthropic API key |
| `DOCKETEER_CLAUDE_CODE_OAUTH_TOKEN` | _(required for claude-code)_ | OAuth token for Claude Code |
| `DOCKETEER_ANTHROPIC_MODEL_SMART` | `claude-opus-4-6` | Model for the `smart` tier |
| `DOCKETEER_ANTHROPIC_MODEL_BALANCED` | `claude-sonnet-4-6` | Model for the `balanced` tier |
| `DOCKETEER_ANTHROPIC_MODEL_FAST` | `claude-haiku-4-5-20251001` | Model for the `fast` tier |

Then configure Docketeer to use the Anthropic inference plugin:

```bash
export DOCKETEER_INFERENCE=anthropic
```
