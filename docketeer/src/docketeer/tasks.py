"""Docket task handlers — bridges scheduled tasks to the brain."""

import logging
from datetime import datetime

from anthropic import AuthenticationError, PermissionDeniedError

from docketeer.brain import APOLOGY, Brain
from docketeer.chat import ChatClient
from docketeer.cycles import consolidation, reverie
from docketeer.dependencies import CurrentBrain, CurrentChatClient
from docketeer.prompt import BrainResponse, MessageContent

log = logging.getLogger(__name__)


async def nudge(
    prompt: str,
    room_id: str = "",
    thread_id: str = "",
    brain: Brain = CurrentBrain(),
    client: ChatClient = CurrentChatClient(),
) -> None:
    """Nudge the brain with a prompt, optionally sending the response to a room."""
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    content = MessageContent(
        username="system", timestamp=now, text=prompt, thread_id=thread_id
    )

    context_room = room_id or "__tasks__"
    try:
        response: BrainResponse = await brain.process(context_room, content)
    except (AuthenticationError, PermissionDeniedError):
        raise
    except Exception:
        log.exception("Error processing nudge task")
        if room_id:
            await client.send_message(room_id, APOLOGY, thread_id=thread_id)
        return

    if room_id and response.text:
        await client.send_message(room_id, response.text, thread_id=thread_id)


docketeer_tasks = [nudge, reverie, consolidation]
