"""Agentic tool-use loop: streaming, tool execution, cache management."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

import anthropic
from anthropic.types import (
    MessageParam,
    TextBlock,
    ThinkingConfigEnabledParam,
    ToolResultBlockParam,
    ToolUseBlock,
)

from docketeer.audit import audit_log, log_usage, record_usage
from docketeer.prompt import CacheControl, SystemBlock
from docketeer.tools import ToolContext, ToolDefinition, registry

if TYPE_CHECKING:
    from docketeer.brain.core import InferenceModel

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 25


async def agentic_loop(
    client: anthropic.AsyncAnthropic,
    model: InferenceModel,
    system: list[SystemBlock],
    messages: list[MessageParam],
    tools: list[ToolDefinition],
    tool_context: ToolContext,
    audit_path: Path,
    usage_path: Path,
    callbacks_on_first_text: Callable[[], Awaitable[None]] | None,
    callbacks_on_text: Callable[[str], Awaitable[None]] | None,
    callbacks_on_tool_start: Callable[[str], Awaitable[None]] | None,
    callbacks_on_tool_end: Callable[[], Awaitable[None]] | None,
    interrupted: asyncio.Event | None = None,
    *,
    thinking: bool = False,
) -> str:
    """Run the tool-use loop and return the final reply text."""
    used_tools = False
    rounds = 0
    exhausted = True
    for _ in range(MAX_TOOL_ROUNDS):
        if interrupted and interrupted.is_set():
            log.info("Agentic loop interrupted by new message")
            return ""
        rounds += 1
        response = await stream_message(
            client,
            model,
            system,
            messages,
            tools,
            on_first_text=callbacks_on_first_text,
            thinking=thinking,
        )

        log_usage(model.model_id, response.usage)
        record_usage(usage_path, model.model_id, response.usage)

        tool_blocks = [b for b in response.content if isinstance(b, ToolUseBlock)]
        if tool_blocks:
            text = "\n".join(
                b.text for b in response.content if isinstance(b, TextBlock)
            ).strip()
            if text and callbacks_on_text:
                await callbacks_on_text(text)
            used_tools = True
            if callbacks_on_tool_start:
                for block in tool_blocks:
                    await callbacks_on_tool_start(block.name)
            tool_results = await execute_tools(tool_blocks, tool_context, audit_path)
            if callbacks_on_tool_end:
                await callbacks_on_tool_end()
            update_cache_breakpoints(messages, tool_results)
            messages.append(MessageParam(role="assistant", content=response.content))
            messages.append(MessageParam(role="user", content=tool_results))
        elif response.stop_reason == "max_tokens":
            log.warning("Response truncated at %d tokens", model.max_output_tokens)
            exhausted = False
            break
        else:
            exhausted = False
            break

    if exhausted and used_tools:
        log.info("Tool round limit reached (%d), nudging for a text reply", rounds)
        messages.append(MessageParam(role="assistant", content=response.content))
        messages.append(
            MessageParam(
                role="user",
                content=(
                    "[system: you've used all your tool rounds for this turn — "
                    "please reply with a summary of what you found or did]"
                ),
            )
        )
        response = await stream_message(
            client,
            model,
            system,
            messages,
            tools=[],
            on_first_text=callbacks_on_first_text,
            thinking=thinking,
        )
        log_usage(model.model_id, response.usage)
        record_usage(usage_path, model.model_id, response.usage)

    return build_reply(response, used_tools, rounds)


async def stream_message(
    client: anthropic.AsyncAnthropic,
    model: InferenceModel,
    system: list[SystemBlock],
    messages: list[MessageParam],
    tools: list[ToolDefinition],
    on_first_text: Callable[[], Awaitable[None]] | None = None,
    *,
    thinking: bool = False,
) -> anthropic.types.Message:
    """Stream a response from Claude, optionally firing a callback on first text."""
    thinking_config: ThinkingConfigEnabledParam | anthropic.Omit = (
        ThinkingConfigEnabledParam(type="enabled", budget_tokens=model.thinking_budget)
        if thinking and model.thinking_budget
        else anthropic.omit
    )
    async with client.messages.stream(
        model=model.model_id,
        max_tokens=model.max_output_tokens,
        thinking=thinking_config,
        system=[b.to_api_dict() for b in system],
        messages=messages,
        tools=[t.to_api_dict() for t in tools],
    ) as stream:
        if on_first_text:
            async for _text in stream.text_stream:
                await on_first_text()
                break
        return await stream.get_final_message()


async def execute_tools(
    tool_blocks: list[ToolUseBlock],
    tool_context: ToolContext,
    audit_path: Path,
) -> list[ToolResultBlockParam]:
    """Run each tool, log calls/results, write audit log, return tool_result dicts."""
    tool_results: list[ToolResultBlockParam] = []
    for block in tool_blocks:
        log.info("Tool call: %s(%s)", block.name, block.input)
        result = await registry.execute(block.name, block.input, tool_context)
        is_error = result.startswith("Error:")
        log.info("Tool result: %s", result[:100])

        audit_log(
            audit_path,
            block.name,
            block.input,
            result,
            is_error,
        )

        tool_results.append(
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
                "is_error": is_error,
            }
        )
    return tool_results


def update_cache_breakpoints(
    messages: list[MessageParam], tool_results: list[ToolResultBlockParam]
) -> None:
    """Move the cache breakpoint to the latest tool result."""
    for prev_msg in messages:
        if prev_msg["role"] != "user" or not isinstance(prev_msg["content"], list):
            continue
        for block in prev_msg["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                block.pop("cache_control", None)  # type: ignore[misc]

    tool_results[-1]["cache_control"] = CacheControl().to_api_dict()


def build_reply(
    response: anthropic.types.Message, had_tool_use: bool, rounds: int
) -> str:
    """Extract the final reply text from a response."""
    reply_parts = [
        block.text for block in response.content if isinstance(block, TextBlock)
    ]

    if response.stop_reason == "max_tokens" and not had_tool_use:
        reply_parts.append(
            "\n\n(I hit my response length limit — ask me to continue if I got cut off)"
        )

    if not reply_parts:
        if had_tool_use:
            log.info("Tool-only response, no text to send (rounds=%d)", rounds)
            return ""
        types = [getattr(b, "type", type(b).__name__) for b in response.content]
        log.warning(
            "No text in response: stop=%s, blocks=%s, rounds=%d/%d",
            response.stop_reason,
            types,
            rounds,
            MAX_TOOL_ROUNDS,
        )
        return "(no response)"

    return "\n".join(reply_parts).strip()
