# docketeer-imap

IMAP IDLE band plugin. Registers a `docketeer.bands` entry point that monitors
IMAP mailboxes for new messages via IDLE (RFC 2177) and produces signals for
the antenna system.

## Structure

- **`band.py`** — `ImapBand` class: connection-per-listen (no persistent client
  in context manager). Parses vault secret for connection details, connects via
  `aioimaplib.IMAP4_SSL`, selects the topic as the mailbox, and loops IDLE to
  detect new messages. Supports catch-up from `last_signal_id` via UID SEARCH.
  All filtering is client-side.

- **`parsing.py`** — `ParsedEmail` dataclass and `parse_email()` function. Uses
  stdlib `email` to extract headers, prefer text/plain body with HTML-stripped
  fallback, and decode RFC 2047 encoded headers. Body truncated at 10,000 chars.

## Testing

IMAP connections are faked with a `FakeImapClient` that implements the same
interface as `aioimaplib.IMAP4_SSL`. Messages are stored as `dict[int, bytes]`
mapping UIDs to raw RFC822 bytes. IDLE cycles return EXISTS once per configured
new UID, then STOP_WAIT_SERVER_PUSH to end the loop.
