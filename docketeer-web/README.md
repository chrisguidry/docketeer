# docketeer-web

Web tools plugin for [Docketeer](https://pypi.org/project/docketeer/). Gives
the agent the ability to search the web, make HTTP requests, and download files
into its workspace.

Install `docketeer-web` alongside `docketeer` and the tools are automatically
available.

## Tools

- **`web_search`** — search the web via the [Brave Search API](https://brave.com/search/api/)
- **`web_request`** — make HTTP requests with content-aware body handling (HTML
  text extraction, large response summarization)
- **`download_file`** — download a file from a URL into the agent's workspace

## Configuration

| Variable                  | Default   | Description                                                            |
|---------------------------|-----------|------------------------------------------------------------------------|
| `DOCKETEER_BRAVE_API_KEY` | _(empty)_ | Brave Search API key. Without this, `web_search` won't return results. |

The `web_request` and `download_file` tools work without any additional
configuration.
