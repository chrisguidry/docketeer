"""Semantic search tool for the agent."""

from docketeer.tools import ToolContext, registry


@registry.tool(emoji=":mag:")
async def semantic_search(ctx: ToolContext, query: str, limit: int = 10) -> str:
    """Search workspace files by meaning, not just exact text matches.
    Use this when you need to find files related to a topic or concept.

    query: what you're looking for (natural language)
    limit: maximum number of results (default 10)
    """
    results = await ctx.search.search(query, limit=limit)
    if not results:
        return f"No results for '{query}'"
    lines: list[str] = []
    for r in results:
        lines.append(f"  {r.path} (score: {r.score:.3f})")
        snippet = r.snippet.replace("\n", " ")[:120]
        lines.append(f"    {snippet}")
    return f"{len(results)} result(s):\n" + "\n".join(lines)
