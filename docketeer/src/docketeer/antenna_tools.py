"""Antenna tools — tune, detune, list_tunings, list_bands."""

from docketeer.antenna import Antenna, SignalFilter, Tuning
from docketeer.tools import ToolContext, registry


def register_antenna_tools(antenna: Antenna) -> None:
    """Register antenna management tools."""

    @registry.tool(emoji=":satellite:")
    async def tune(
        ctx: ToolContext,
        name: str,
        band: str,
        topic: str,
        line: str = "",
        filters: list[dict[str, str]] | None = None,
        batch_window: float = 5.0,
        max_batch: int = 10,
    ) -> str:
        """Start listening to a realtime event stream. Matching events are
        batched and delivered to a line for you to reason about — like
        GitHub webhook events arriving on an "opensource" line, or Bluesky
        mentions landing on a "bluesky-mentions" line.

        name: unique name for this tuning (e.g. "github-prs", "bluesky-mentions")
        band: which band to listen on (use list_bands to see what's available)
        topic: what to listen for — meaning depends on the band (e.g. event type, collection)
        line: which line to deliver events to (defaults to the tuning name).
            Use the same line for related tunings so you build up shared context.
        filters: optional list of filters to narrow events, each with path/op/value keys
            (e.g. {"path": "payload.action", "op": "eq", "value": "opened"})
        batch_window: seconds to wait and batch events before delivery (default 5.0)
        max_batch: max events per batch (default 10)
        """
        parsed_filters = [
            SignalFilter(path=f["path"], op=f["op"], value=f.get("value", ""))
            for f in (filters or [])
        ]
        tuning = Tuning(
            name=name,
            band=band,
            topic=topic,
            line=line,
            filters=parsed_filters,
            batch_window=batch_window,
            max_batch=max_batch,
        )
        try:
            await antenna.tune(tuning)
        except ValueError as e:
            return f"Error: {e}"

        target = line or name
        return f"Tuned '{name}' on band '{band}', delivering to line '{target}'"

    @registry.tool(emoji=":satellite:")
    async def detune(ctx: ToolContext, name: str) -> str:
        """Stop listening to a tuning and remove it.

        name: the tuning name to remove (e.g. "github-prs")
        """
        try:
            await antenna.detune(name)
        except KeyError:
            return f"Error: no tuning named '{name}'"
        return f"Detuned '{name}'"

    @registry.tool(emoji=":satellite:")
    async def list_tunings(ctx: ToolContext) -> str:
        """Show what you're currently listening to — all active tunings
        and which lines they deliver to."""
        tunings = antenna.list_tunings()
        if not tunings:
            return "No tunings configured."

        lines: list[str] = []
        for t in tunings:
            target = t.target_line
            filter_count = len(t.filters)
            filters_desc = f" ({filter_count} filter(s))" if filter_count else ""
            lines.append(
                f"  [{t.name}] band={t.band} topic={t.topic} "
                f"→ line '{target}'{filters_desc}"
            )
        return f"{len(tunings)} tuning(s):\n" + "\n".join(lines)

    @registry.tool(emoji=":satellite:")
    async def list_bands(ctx: ToolContext) -> str:
        """Show available bands — the event sources you can tune into
        (e.g. wicket for SSE webhooks, atproto for Bluesky events)."""
        bands = antenna.list_bands()
        if not bands:
            return "No bands available."
        return f"{len(bands)} band(s):\n" + "\n".join(f"  - {b}" for b in bands)
