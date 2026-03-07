# docketeer-deepinfra

DeepInfra inference backend plugin for Docketeer.

This plugin provides inference through the DeepInfra API (OpenAI-compatible).

## Installation

```bash
pip install docketeer-deepinfra
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DOCKETEER_DEEPINFRA_API_KEY` | _(required)_ | DeepInfra API key |
| `DOCKETEER_DEEPINFRA_BASE_URL` | `https://api.deepinfra.com/v1/openai` | API base URL |
| `DOCKETEER_DEEPINFRA_MODEL` | `MiniMaxAI/MiniMax-M2.5` | Default model for all tiers |
| `DOCKETEER_DEEPINFRA_MODEL_SMART` | _(falls back to MODEL)_ | Model for the `smart` tier |
| `DOCKETEER_DEEPINFRA_MODEL_BALANCED` | _(falls back to MODEL)_ | Model for the `balanced` tier |
| `DOCKETEER_DEEPINFRA_MODEL_FAST` | _(falls back to MODEL)_ | Model for the `fast` tier |

Then configure Docketeer to use the DeepInfra inference plugin:

```bash
export DOCKETEER_INFERENCE=deepinfra
```
