# docketeer-imap

IMAP IDLE band plugin for [Docketeer](https://pypi.org/project/docketeer/).
Monitors IMAP mailboxes for new messages using
[IDLE](https://www.rfc-editor.org/rfc/rfc2177) (push-style notifications) and
produces `Signal` objects for the antenna system.

Install `docketeer-imap` alongside `docketeer` and the band is automatically
available.

## Configuration

All connection details come from a vault secret — no global environment
variables needed. Each tuning specifies its own secret, so you can monitor
multiple IMAP accounts independently.

The vault secret must be a JSON object:

```json
{
  "host": "imap.gmail.com",
  "port": 993,
  "username": "me@gmail.com",
  "password": "your-app-password"
}
```

For Gmail, use an [App Password](https://support.google.com/accounts/answer/185833)
rather than your account password.

## Signals

Each new email produces a signal with:

- **signal_id** — IMAP UID (used for catch-up on reconnect)
- **topic** — the mailbox name (e.g. `INBOX`)
- **payload** — `{from, to, cc, subject, date, message_id, body, headers}`
- **summary** — `"From: sender — Subject: subject line"`

The `headers` dict contains message headers with noisy infrastructure headers
(DKIM signatures, ARC chains, spam reports, MTA routing, etc.) filtered out by
default. The remaining headers are the ones useful for filtering and context.

To customize which headers are blocked, set
`DOCKETEER_IMAP_BLOCKED_HEADER_PREFIXES` to a comma-separated list of
case-insensitive prefixes:

```sh
# Only block spam-related headers
export DOCKETEER_IMAP_BLOCKED_HEADER_PREFIXES="X-Spam-,SpamTally"

# Disable all header filtering
export DOCKETEER_IMAP_BLOCKED_HEADER_PREFIXES=""
```

The default blocked prefixes are: `ARC-`, `Authentication-Results`, `DKIM-`,
`DKIMCheck`, `MIME-Version`, `Received`, `Return-Path`, `SpamTally`,
`X-Brightmail-`, `X-DKIM`, `X-Forwarded-`, `X-Gm-`, `X-Google-`,
`X-Originating-IP`, `X-Received`, `X-Spam-`, `X-Zone-`.

You can filter on any header that passes through:

```
{path: "payload.headers.X-GitHub-Event", op: "eq", value: "pull_request"}
{path: "payload.from", op: "contains", value: "github.com"}
{path: "payload.subject", op: "icontains", value: "deploy"}
```

## Filtering

All filtering is client-side for v1. `remote_filter_hints()` returns an empty
list.
