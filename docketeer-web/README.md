# docketeer-web

Web tools plugin for [Docketeer](../README.md). Gives the agent the ability to
search the web, make HTTP requests, and download files.

## Tools

- **`web_search`** — search the web via the [Brave Search API](https://brave.com/search/api/)
- **`web_request`** — make HTTP requests with content-aware body handling
- **`download_file`** — download a file into the agent's workspace

## Setup

For web search, you'll need a Brave Search API key. Add it to your
`.envrc.private`:

```sh
export DOCKETEER_BRAVE_API_KEY="BSA..."
```

The `web_request` and `download_file` tools work without any additional
configuration.

## Environment variables

| Variable                  | Default   | Description                                                            |
|---------------------------|-----------|------------------------------------------------------------------------|
| `DOCKETEER_BRAVE_API_KEY` | _(empty)_ | Brave Search API key. Without this, `web_search` won't return results. |
