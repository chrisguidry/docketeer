# docketeer-tui

Terminal chat backend. Implements the `docketeer.chat` entry point for
interactive local use via prompt-toolkit and rich. Also provides a
`docketeer.prompt` entry point for TUI-specific context.

## Structure

- **`client.py`** — the `TUIClient`. Implements `ChatClient` with a
  terminal-based UI using prompt-toolkit for input and rich for output
  formatting.
- **`prompt.py`** — prompt provider that adds TUI-specific context to the
  system prompt (terminal capabilities, display hints).

## Testing

Tests verify the client lifecycle and prompt generation. The TUI rendering
is tested through its public interface, not by inspecting terminal output.
