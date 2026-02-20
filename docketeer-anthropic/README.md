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

Set the backend type with `DOCKETEER_ANTHROPIC_BACKEND`:

```bash
# Use Anthropic API (default)
export DOCKETEER_ANTHROPIC_BACKEND=api
export DOCKETEER_ANTHROPIC_API_KEY=your-api-key-here

# Use claude-code backend
export DOCKETEER_ANTHROPIC_BACKEND=claude-code
export DOCKETEER_CLAUDE_CODE_OAUTH_TOKEN=your-oauth-token-here
```

Then configure Docketeer to use the Anthropic inference plugin:

```bash
export DOCKETEER_INFERENCE=anthropic
```
