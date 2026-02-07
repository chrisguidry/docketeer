"""Docket task handlers — bridges scheduled tasks to the brain."""

from datetime import datetime

from docketeer.brain import Brain
from docketeer.chat import ChatClient
from docketeer.cycles import consolidation, reverie
from docketeer.prompt import BrainResponse, MessageContent

_brain: Brain | None = None
_client: ChatClient | None = None


def set_brain(brain: Brain) -> None:
    global _brain
    _brain = brain


def set_client(client: ChatClient) -> None:
    global _client
    _client = client


def get_brain() -> Brain:
    if _brain is None:
        raise RuntimeError("Brain not initialized — call set_brain() first")
    return _brain


def get_client() -> ChatClient:
    if _client is None:
        raise RuntimeError("ChatClient not initialized — call set_client() first")
    return _client


async def nudge(prompt: str, room_id: str = "") -> None:
    """Nudge the brain with a prompt, optionally sending the response to a room."""
    brain = get_brain()
    client = get_client()

    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    content = MessageContent(username="system", timestamp=now, text=prompt)

    context_room = room_id or "__tasks__"
    response: BrainResponse = await brain.process(context_room, content)

    if room_id and response.text:
        await client.send_message(room_id, response.text)


docketeer_tasks = [nudge, reverie, consolidation]
