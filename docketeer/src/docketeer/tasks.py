"""Docket task handlers — bridges scheduled tasks to the brain."""

import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter
from docket.dependencies import Perpetual

from docketeer import environment
from docketeer.brain import APOLOGY, CHAT_MODEL, Brain
from docketeer.brain.backend import BackendAuthError
from docketeer.chat import ChatClient
from docketeer.cycles import consolidation, reverie
from docketeer.dependencies import CurrentBrain, CurrentChatClient
from docketeer.prompt import BrainResponse, MessageContent

log = logging.getLogger(__name__)

_consecutive_failures: dict[str, int] = {}

_ISO_DURATION_RE = re.compile(
    r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$",
    re.IGNORECASE,
)


def parse_every(every: str) -> timedelta | None:
    """Parse an ISO 8601 duration string into a timedelta.

    Returns None if the string isn't a valid ISO 8601 duration, meaning the
    caller should treat it as a cron expression instead.
    """
    m = _ISO_DURATION_RE.match(every)
    if not m or not any(m.groups()):
        return None
    days = int(m.group(1) or 0)
    hours = int(m.group(2) or 0)
    minutes = int(m.group(3) or 0)
    seconds = int(m.group(4) or 0)
    return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


async def nudge(
    prompt: str,
    room_id: str = "",
    thread_id: str = "",
    model: str = "",
    brain: Brain = CurrentBrain(),
    client: ChatClient = CurrentChatClient(),
) -> None:
    """Nudge the brain with a prompt, optionally sending the response to a room."""
    now = datetime.now().astimezone()
    content = MessageContent(
        username="system", timestamp=now, text=prompt, thread_id=thread_id
    )

    context_room = room_id or "__tasks__"
    key = f"nudge:{room_id or '__tasks__'}"
    try:
        response: BrainResponse = await brain.process(
            context_room, content, model=model or CHAT_MODEL
        )
    except BackendAuthError:
        raise
    except Exception:
        _consecutive_failures[key] = _consecutive_failures.get(key, 0) + 1
        level = logging.ERROR if _consecutive_failures[key] >= 3 else logging.WARNING
        log.log(
            level,
            "Error processing nudge task (attempt %d)",
            _consecutive_failures[key],
            exc_info=True,
        )
        if room_id:
            await client.send_message(room_id, APOLOGY, thread_id=thread_id)
        return
    _consecutive_failures.pop(key, None)

    if room_id and response.text:
        await client.send_message(room_id, response.text, thread_id=thread_id)


async def nudge_every(
    prompt: str,
    every: str,
    timezone: str = "",
    room_id: str = "",
    thread_id: str = "",
    model: str = "",
    perpetual: Perpetual = Perpetual(),
    brain: Brain = CurrentBrain(),
    client: ChatClient = CurrentChatClient(),
) -> None:
    """Recurring nudge — fires on a fixed interval or cron schedule."""
    duration = parse_every(every)

    now = datetime.now().astimezone()
    content = MessageContent(
        username="system", timestamp=now, text=prompt, thread_id=thread_id
    )

    context_room = room_id or "__tasks__"
    key = f"nudge_every:{room_id or '__tasks__'}"
    try:
        response: BrainResponse = await brain.process(
            context_room, content, model=model or CHAT_MODEL
        )
    except BackendAuthError:
        raise
    except Exception:
        _consecutive_failures[key] = _consecutive_failures.get(key, 0) + 1
        level = logging.ERROR if _consecutive_failures[key] >= 3 else logging.WARNING
        log.log(
            level,
            "Error processing recurring nudge task (attempt %d)",
            _consecutive_failures[key],
            exc_info=True,
        )
        if room_id:
            await client.send_message(room_id, APOLOGY, thread_id=thread_id)
    else:
        _consecutive_failures.pop(key, None)
        if room_id and response.text:
            await client.send_message(room_id, response.text, thread_id=thread_id)

    if duration:
        perpetual.after(duration)
    else:
        tz = ZoneInfo(timezone) if timezone else environment.local_timezone()
        now_in_tz = datetime.now(tz)
        next_time = croniter(every, now_in_tz).get_next(datetime)
        perpetual.at(next_time)


docketeer_tasks = [nudge, nudge_every, reverie, consolidation]
