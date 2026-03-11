"""Agentic tool-use loop: streaming, tool execution using OpenAI SDK."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from openai import AsyncOpenAI, LengthFinishReasonError
from openai.lib.streaming.chat import ChatCompletionStreamState
from openai.types.chat import ChatCompletion, ChatCompletionMessageToolCall

from docketeer.audit import audit_log, log_usage, record_usage
from docketeer.brain.backend import Usage
from docketeer.prompt import ImageBlockParam, MessageParam, SystemBlock, TextBlockParam
from docketeer.tools import WRAP_UP_TOOL_NAME, ToolContext, ToolDefinition, registry

if TYPE_CHECKING:
    from docketeer.brain.core import InferenceModel

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 25


async def agentic_loop(
    client: AsyncOpenAI,
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
    default_model: str = "meta-llama/Llama-3.3-70B-Instruct",
) -> str:
    """Run the tool-use loop and return the final reply text."""
    used_tools = False
    rounds = 0
    exhausted = True

    for _ in range(MAX_TOOL_ROUNDS):
        if interrupted and interrupted.is_set():  # pragma: no cover
            log.info("Agentic loop interrupted")
            return ""
        rounds += 1

        # Always pass tools - the model needs them to understand tool results
        # (unlike Anthropic which has different behavior)
        effective_tools = tools

        response = await stream_message(
            client,
            model,
            system,
            messages,
            effective_tools,
            on_first_text=callbacks_on_first_text,
            on_text=callbacks_on_text,
            default_model=default_model,
        )

        # Log usage
        cached_tokens = 0
        if response.usage and response.usage.prompt_tokens_details:
            # Handle both real PromptTokensDetails and mock objects
            cached_tokens_attr = response.usage.prompt_tokens_details.cached_tokens
            if isinstance(cached_tokens_attr, int):
                cached_tokens = cached_tokens_attr

        usage = Usage(
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            cache_read_input_tokens=cached_tokens,
            cache_creation_input_tokens=0,  # Cache creation tracked separately if available
        )
        log_usage(model.model_id, usage)
        record_usage(usage_path, model.model_id, usage)

        # Extract tool calls from response
        message = response.choices[0].message
        tool_calls = message.tool_calls or []
        finish_reason = response.choices[0].finish_reason

        log.debug(
            "RESPONSE: content=%r, tool_calls=%s, finish_reason=%s",
            message.content,
            [(tc.id, tc.function.name) for tc in tool_calls],  # type: ignore[union-attr]
            finish_reason,
        )

        if tool_calls:
            used_tools = True
            log.info("Tool calls: %s", [(tc.id, tc.function.name) for tc in tool_calls])  # type: ignore[union-attr]

            # Notify callbacks
            if callbacks_on_tool_start:
                for tc in tool_calls:
                    await callbacks_on_tool_start(tc.function.name)  # type: ignore[union-attr]

            # Execute tools
            tool_results = await execute_tools(tool_calls, tool_context, audit_path)  # type: ignore[arg-type]

            if callbacks_on_tool_end:
                await callbacks_on_tool_end()

            # Add assistant message with tool calls
            messages.append(
                MessageParam(
                    role="assistant",
                    content=message.content or "",
                    tool_calls=[tc.model_dump() for tc in tool_calls],
                )
            )

            # Add tool result messages
            for tr in tool_results:
                messages.append(
                    MessageParam(
                        role="tool",
                        content=tr["content"],
                        tool_call_id=tr["tool_call_id"],
                    )
                )

            if any(tc.function.name == WRAP_UP_TOOL_NAME for tc in tool_calls):  # type: ignore[union-attr]
                return ""

        elif response.choices[0].finish_reason == "length":
            log.warning("Response truncated")
            exhausted = False
            break
        else:
            exhausted = False
            break

    # If we hit tool round limit, ask for summary
    if exhausted and used_tools:
        log.info("Tool round limit reached, asking for summary")
        messages.append(
            MessageParam(
                role="user",
                content="[system: you've used all your tool rounds — please reply with a summary]",
            )
        )
        response = await stream_message(
            client,
            model,
            system,
            messages,
            [],
            on_first_text=callbacks_on_first_text,
            on_text=callbacks_on_text,
            default_model=default_model,
        )
        cached_tokens = 0
        if response.usage and response.usage.prompt_tokens_details:
            cached_tokens_attr = response.usage.prompt_tokens_details.cached_tokens
            if isinstance(cached_tokens_attr, int):
                cached_tokens = cached_tokens_attr

        usage = Usage(
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            cache_read_input_tokens=cached_tokens,
            cache_creation_input_tokens=0,
        )
        log_usage(model.model_id, usage)
        record_usage(usage_path, model.model_id, usage)

    return build_reply(response, used_tools, rounds)


async def stream_message(
    client: AsyncOpenAI,
    model: InferenceModel,
    system: list[SystemBlock],
    messages: list[MessageParam],
    tools: list[ToolDefinition],
    on_first_text: Callable[[], Awaitable[None]] | None = None,
    on_text: Callable[[str], Awaitable[None]] | None = None,
    default_model: str | None = None,
) -> ChatCompletion:
    """Stream a response from DeepInfra."""
    model_id = model.model_id or default_model
    serialized_messages = _serialize_messages(system, messages)
    serialized_tools = [_tool_to_dict(t) for t in tools] if tools else None

    log.info(
        "Request: model=%s, tools=%d, messages=%d",
        model_id,
        len(serialized_tools or []),
        len(serialized_messages),
    )

    state = ChatCompletionStreamState()
    first_text_fired = False

    raw_stream = await client.chat.completions.create(  # type: ignore[no-matching-overload]
        model=model_id,
        messages=serialized_messages,
        tools=serialized_tools,
        tool_choice="auto" if serialized_tools else None,
        max_tokens=model.max_output_tokens,
        stream=True,
        stream_options={"include_usage": True},
    )

    async for chunk in raw_stream:
        state.handle_chunk(chunk)

        if chunk.choices:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                if not first_text_fired and on_first_text:
                    await on_first_text()
                    first_text_fired = True
                if on_text:
                    await on_text(delta.content)

    try:
        return state.get_final_completion()
    except LengthFinishReasonError as exc:
        return exc.completion


def _serialize_messages(
    system: list[SystemBlock],
    messages: list[MessageParam],
) -> list[dict]:
    """Serialize messages for OpenAI API."""
    result = []

    # Add system message
    if system:
        system_content = "\n".join(block.text for block in system)
        result.append({"role": "system", "content": system_content})

    # Add conversation messages
    for msg in messages:
        msg_dict: dict = {"role": msg.role}

        # Add tool_call_id for tool role messages
        if msg.tool_call_id:
            msg_dict["tool_call_id"] = msg.tool_call_id

        # Handle content
        if isinstance(msg.content, str):
            msg_dict["content"] = msg.content
        elif isinstance(msg.content, list):
            # Normal content list
            serialized_content = []
            for b in msg.content:
                if isinstance(b, (TextBlockParam, ImageBlockParam)):
                    serialized_content.append(b.to_dict())
                elif isinstance(b, dict):
                    serialized_content.append(b)
                else:
                    serialized_content.append(  # pragma: no cover
                        {"type": "text", "text": str(b)}
                    )
            msg_dict["content"] = serialized_content
        else:
            msg_dict["content"] = (
                str(msg.content) if msg.content else ""
            )  # pragma: no cover

        # Handle tool_calls attribute
        if msg.tool_calls:
            msg_dict["tool_calls"] = msg.tool_calls

        result.append(msg_dict)

    return result


async def execute_tools(
    tool_calls: list[ChatCompletionMessageToolCall],
    tool_context: ToolContext,
    audit_path: Path,
) -> list[dict]:
    """Execute tools and return results."""
    results = []

    for tc in tool_calls:
        name = tc.function.name
        args_str = tc.function.arguments

        try:
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
        except json.JSONDecodeError:
            args = {}

        log.info("Executing tool: %s(%s)", name, args)
        result = await registry.execute(name, args, tool_context)
        is_error = result.startswith("Error:")

        audit_log(audit_path, name, args, result, is_error)

        results.append(
            {
                "tool_call_id": tc.id,
                "content": result,
                "is_error": is_error,
            }
        )

    return results


def build_reply(response: ChatCompletion, had_tool_use: bool, rounds: int) -> str:
    """Extract reply text from response."""
    if not response.choices:
        return "(no response)"

    message = response.choices[0].message
    content = message.content or ""
    finish_reason = response.choices[0].finish_reason

    if finish_reason == "length" and not had_tool_use:
        content += "\n\n(I hit my response length limit)"

    if not content:
        if had_tool_use:
            return "I ran the tool. What would you like to know about the results?"
        return "(no response)"

    return content.strip()


def _tool_to_dict(tool: ToolDefinition) -> dict:
    """Convert ToolDefinition to OpenAI tool format."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }
