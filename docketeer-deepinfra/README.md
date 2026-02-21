# docketeer-deepinfra

DeepInfra inference backend plugin for Docketeer.

This plugin provides inference through the DeepInfra native API.

## Installation

```bash
pip install docketeer-deepinfra
```

## Configuration

Configure the DeepInfra backend with environment variables:

```bash
# Required: Your DeepInfra API key
export DOCKETEER_DEEPINFRA_API_KEY=your-api-key-here

# Optional: Override the API base URL (defaults to https://api.deepinfra.com)
export DOCKETEER_DEEPINFRA_BASE_URL=https://api.deepinfra.com

# Optional: Set the default model (defaults to meta-llama/Llama-3.3-70B-Instruct)
export DOCKETEER_DEEPINFRA_MODEL=meta-llama/Llama-3.3-70B-Instruct
```

Then configure Docketeer to use the DeepInfra inference plugin:

```bash
export DOCKETEER_INFERENCE=deepinfra
```

## Supported Models

Any model available on DeepInfra can be used. Common models include:

- `meta-llama/Llama-3.3-70B-Instruct` (default)
- `meta-llama/Llama-3.1-405B-Instruct`
- `Qwen/Qwen2.5-72B-Instruct`
- `deepseek-ai/DeepSeek-V3`

Set the model using `DOCKETEER_DEEPINFRA_MODEL` or by specifying the model in your Docketeer configuration.
