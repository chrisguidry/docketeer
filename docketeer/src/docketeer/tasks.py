"""Docket task handlers — bridges scheduled tasks to the brain."""

from datetime import datetime

from docketeer.brain import Brain
from docketeer.chat import ChatClient
from docketeer.cycles import consolidation, reverie
from docketeer.dependencies import CurrentBrain, CurrentChatClient
from docketeer.prompt import BrainResponse, MessageContent


async def nudge(
    prompt: str,
    room_id: str = "",
    brain: Brain = CurrentBrain(),
    client: ChatClient = CurrentChatClient(),
) -> None:
    """Nudge the brain with a prompt, optionally sending the response to a room."""
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    content = MessageContent(username="system", timestamp=now, text=prompt)

    context_room = room_id or "__tasks__"
    response: BrainResponse = await brain.process(context_room, content)

    if room_id and response.text:
        await client.send_message(room_id, response.text)


docketeer_tasks = [nudge, reverie, consolidation]
