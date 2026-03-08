"""Antenna tools — tune, detune, list_tunings, list_bands."""

from typing import TypedDict, cast

from docketeer.antenna import Antenna, FilterOp, SignalFilter, Tuning
from docketeer.tools import ToolContext, registry


class _FilterSpecRequired(TypedDict):
    path: str
    op: FilterOp


class FilterSpec(_FilterSpecRequired, total=False):
    """A filter specification for narrowing events."""

    value: str


def register_antenna_tools(antenna: Antenna) -> None:
    """Register antenna management tools."""

    @registry.tool(emoji=":satellite:")
    async def tune(
        ctx: ToolContext,
        name: str,
        band: str,
        topic: str,
        line: str = "",
        filters: list[FilterSpec] | None = None,
        secret: str | None = None,
    ) -> str:
        """Start listening to a realtime event stream. Each matching event is
        delivered to a line for you to reason about — like GitHub webhook
        events arriving on an "opensource" line, or Bluesky mentions landing
        on a "bluesky-mentions" line.

        name: unique name for this tuning (e.g. "github-prs", "bluesky-mentions")
        band: which band to listen on (use list_bands to see what's available)
        topic: what to listen for — meaning depends on the band (e.g. event type, collection)
        line: which line to deliver events to (defaults to the tuning name).
            Use the same line for related tunings so you build up shared context.
        filters: optional list of filters to narrow events, each with path/op/value keys.
            ops: eq, ne, contains, icontains (case-insensitive), startswith, exists
            (e.g. {{"path": "payload.action", "op": "eq", "value": "opened"}})
            (e.g. {{"path": "payload.record.text", "op": "icontains", "value": "cat"}})
        secret: name of a vault secret for authentication (e.g. "wicket/github-token").
            The secret is resolved when the tuning connects.
        """
        parsed_filters = [
            SignalFilter(
                path=f["path"],
                op=cast(FilterOp, f["op"]),
                value=f.get("value", ""),
            )
            for f in (filters or [])
        ]
        tuning = Tuning(
            name=name,
            band=band,
            topic=topic,
            line=line,
            filters=parsed_filters,
            secret=secret,
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
        (e.g. wicket for SSE webhooks, atproto for Bluesky events).
        Each band describes how topic, filters, and secret map to that platform."""
        bands = antenna.list_bands()
        if not bands:
            return "No bands available."

        sections: list[str] = []
        for band in bands:
            header = f"  [{band.name}]"
            if band.description:
                header += f"\n{_indent(band.description, 4)}"
            sections.append(header)
        return f"{len(bands)} band(s):\n\n" + "\n\n".join(sections)


def _indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(f"{prefix}{line}" for line in text.strip().splitlines())
