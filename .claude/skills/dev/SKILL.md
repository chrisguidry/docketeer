---
name: dev
description: Start or health-check docketeer in dev mode
---

Start docketeer in dev mode (with live reload) as a background process so you can monitor its output during development.

## Steps

1. **Check if already running**: Use `pgrep -f "docketeer start"` to see if a docketeer process exists.

2. **If running, health-check it**: Read the tail of the background task output file (check `/tmp/claude-*/**/tasks/*.output` or use TaskOutput with block=false if you have the task ID). Look for signs it's healthy vs borked:
   - **Healthy**: recent "Listening for messages" or normal HTTP request logs, no repeated tracebacks
   - **Borked**: repeated exceptions/tracebacks in recent output, "Connection refused" or "Connection closed" errors, the process is a zombie or stuck in a restart loop (watchfiles reloading over and over without reaching "Listening")

3. **If borked or not running**:
   - Kill any existing docketeer processes: `pkill -f "docketeer start"` (and wait a moment for cleanup)
   - Start fresh: run `uv run docketeer start --dev` in the background using Bash with `run_in_background: true`
   - Wait a few seconds, then check the output to confirm it connected to Rocket Chat and reached "Listening for messages"

4. **If healthy**: Just report that it's already running and looks good. Show a few recent lines of output so the user can see its state.

5. **Report**: Tell the user the background task ID and whether this was a fresh start or an existing healthy process.
