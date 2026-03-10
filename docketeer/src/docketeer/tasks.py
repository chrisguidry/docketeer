"""Docket task handlers and scheduling hook.

Contains the nudge/nudge_every task handlers that bridge scheduled tasks to
the brain, the SchedulingHook (workspace hook for tasks/ directory), and
the list_scheduled tool.
"""

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from croniter import croniter
from docket import Logged
from docket.dependencies import Perpetual, TaskKey

from docketeer import environment
from docketeer.brain import APOLOGY, CHAT_MODEL, Brain
from docketeer.brain.backend import BackendAuthError
from docketeer.chat import ChatClient
from docketeer.dependencies import CurrentBrain, CurrentChatClient
from docketeer.hooks import (
    HookResult,
    parse_frontmatter,
    render_frontmatter,
    strip_frontmatter,
)
from docketeer.prompt import BrainResponse, MessageContent
from docketeer.tools import ToolContext, registry, safe_path

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
    prompt_file: Annotated[str, Logged],
    line: Annotated[str, Logged] = "",
    room_id: Annotated[str, Logged] = "",
    thread_id: Annotated[str, Logged] = "",
    tier: Annotated[str, Logged] = "",
    brain: Brain = CurrentBrain(),
    client: ChatClient = CurrentChatClient(),
    task_key: str = TaskKey(),
) -> None:
    """Nudge the brain with a prompt from a file.

    The prompt is read from the workspace at prompt_file (relative to workspace root).
    This allows you to write longer prompts, review and edit them, and discuss them
    with the user without needing to modify the scheduled task.
    """
    resolved = safe_path(environment.WORKSPACE_PATH, prompt_file)
    prompt = strip_frontmatter(resolved.read_text())

    if not prompt:
        log.warning("Prompt file is empty: %s", prompt_file)
        return

    now = datetime.now().astimezone()
    content = MessageContent(timestamp=now, text=prompt, thread_id=thread_id)

    target_line = line or f"__task__:{task_key}"
    key = f"nudge:{task_key}"
    try:
        response: BrainResponse = await brain.process(
            target_line, content, tier=tier or CHAT_MODEL, chat_room=room_id
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

    # One-shot tasks are auto-deleted after firing
    if resolved.exists():
        resolved.unlink()
        log.info("Auto-deleted one-shot task file: %s", prompt_file)


async def nudge_every(
    prompt_file: Annotated[str, Logged],
    every: Annotated[str, Logged] = "",
    timezone: Annotated[str, Logged] = "",
    line: Annotated[str, Logged] = "",
    room_id: Annotated[str, Logged] = "",
    thread_id: Annotated[str, Logged] = "",
    tier: Annotated[str, Logged] = "",
    perpetual: Perpetual = Perpetual(),
    brain: Brain = CurrentBrain(),
    client: ChatClient = CurrentChatClient(),
    task_key: str = TaskKey(),
) -> None:
    """Recurring nudge — fires on a fixed interval or cron schedule.

    The prompt is read from the workspace at prompt_file (relative to workspace root).
    This allows you to write longer prompts, review and edit them, and discuss them
    with the user without needing to modify the scheduled task. The prompt file is
    re-read each time the task fires, so you can modify it between runs.
    """
    resolved = safe_path(environment.WORKSPACE_PATH, prompt_file)
    prompt = strip_frontmatter(resolved.read_text())

    if not prompt:
        log.warning("Prompt file is empty: %s", prompt_file)
        return

    duration = parse_every(every)

    now = datetime.now().astimezone()
    content = MessageContent(timestamp=now, text=prompt, thread_id=thread_id)

    target_line = line or f"__task__:{task_key}"
    key = f"nudge_every:{task_key}"
    try:
        response: BrainResponse = await brain.process(
            target_line, content, tier=tier or CHAT_MODEL, chat_room=room_id
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


docketeer_tasks = [nudge, nudge_every]


# --- Scheduling hook ---


class SchedulingHook:
    """Workspace hook for the tasks/ directory."""

    prefix = PurePosixPath("tasks")

    def __init__(self) -> None:
        self._docket: Any = None

    def set_docket(self, docket: Any) -> None:
        self._docket = docket

    @property
    def _docket_required(self) -> Any:
        if self._docket is None:
            raise RuntimeError("SchedulingHook not wired to a Docket")
        return self._docket

    async def validate(self, path: PurePosixPath, content: str) -> HookResult | None:
        """Validate task frontmatter and enrich with task key."""
        if not path.name.endswith(".md"):
            return None

        meta, body = parse_frontmatter(content)
        if not meta:
            raise ValueError(
                f"Task file {path} needs YAML frontmatter with 'every' "
                f"(cron/duration) or 'when' (ISO datetime)"
            )

        name = path.stem
        msg = _validate_schedule(name, meta)

        updated_content: str | None = None
        if meta.get("key") != name:
            meta["key"] = name
            updated_content = render_frontmatter(meta, body)

        return HookResult(msg, updated_content=updated_content)

    async def commit(self, path: PurePosixPath, content: str) -> None:
        """Register the task with Docket."""
        if not path.name.endswith(".md"):
            return

        meta, _ = parse_frontmatter(content)
        name = path.stem
        await self._register_task(name, meta, path)

    async def on_delete(self, path: PurePosixPath) -> str | None:
        """Cancel the Docket task for this file."""
        if not path.name.endswith(".md"):
            return None

        name = path.stem
        docket = self._docket_required
        await docket.cancel(name)
        log.info("Cancelled task '%s'", name)
        return f"Cancelled task '{name}'"

    async def scan(self, workspace: Path) -> None:
        """Reconcile tasks/ files with Docket entries."""
        tasks_dir = workspace / "tasks"
        if not tasks_dir.is_dir():
            return

        for md_file in sorted(tasks_dir.glob("*.md")):
            content = md_file.read_text()
            meta, _ = parse_frontmatter(content)
            if not meta:
                continue

            name = md_file.stem
            rel_path = PurePosixPath(md_file.relative_to(workspace))
            try:
                await self._register_task(name, meta, rel_path)
            except (ValueError, RuntimeError):
                log.warning("Scan: skipping invalid task %s", name, exc_info=True)

    async def _register_task(self, name: str, meta: dict, path: PurePosixPath) -> str:
        docket = self._docket_required

        prompt_file = str(path)
        line = meta.get("line", "")
        silent = meta.get("silent", False)
        tier = meta.get("tier", "")
        timezone = meta.get("timezone", "")
        room_id = ""
        thread_id = ""

        every = meta.get("every")
        when = meta.get("when")

        if every:
            duration = parse_every(str(every))

            if duration is None:
                if timezone:
                    try:
                        tz = ZoneInfo(timezone)
                    except (KeyError, ValueError) as e:
                        raise ValueError(f"Invalid timezone: {timezone}") from e
                else:
                    tz = environment.local_timezone()

                try:
                    now = datetime.now(tz)
                    first_fire = croniter(str(every), now).get_next(datetime)
                except (ValueError, KeyError) as e:
                    raise ValueError(f"Invalid schedule expression: {every}") from e

                mode_desc = f"cron {every}"
            else:
                first_fire = datetime.now().astimezone()
                mode_desc = f"every {every}"

            await docket.replace(nudge_every, when=first_fire, key=name)(
                prompt_file=prompt_file,
                every=str(every),
                timezone=timezone,
                line=line,
                room_id=room_id if not silent else "",
                thread_id=thread_id if not silent else "",
                tier=tier,
            )

            local = first_fire.astimezone().isoformat(timespec="seconds")
            msg = f"Scheduled '{name}' ({mode_desc}), next run {local}"
            log.info(msg)
            return msg

        elif when:
            try:
                fire_at = datetime.fromisoformat(str(when))
            except ValueError as e:
                raise ValueError(f"Invalid datetime: {when}") from e

            await docket.replace(nudge, when=fire_at, key=name)(
                prompt_file=prompt_file,
                line=line,
                room_id=room_id if not silent else "",
                thread_id=thread_id if not silent else "",
                tier=tier,
            )

            local = fire_at.astimezone().isoformat(timespec="seconds")
            msg = f"Scheduled '{name}' for {local}"
            log.info(msg)
            return msg

        else:
            raise ValueError(
                f"Task '{name}' needs 'every' (cron/duration) or 'when' (ISO datetime)"
            )


def _validate_schedule(name: str, meta: dict) -> str:
    """Validate schedule metadata without side effects. Returns the message."""
    every = meta.get("every")
    when = meta.get("when")
    timezone = meta.get("timezone", "")

    if every:
        duration = parse_every(str(every))
        if duration is None:
            if timezone:
                try:
                    ZoneInfo(timezone)
                except (KeyError, ValueError) as e:
                    raise ValueError(f"Invalid timezone: {timezone}") from e
            try:
                tz = ZoneInfo(timezone) if timezone else environment.local_timezone()
                now = datetime.now(tz)
                first_fire = croniter(str(every), now).get_next(datetime)
            except (ValueError, KeyError) as e:
                raise ValueError(f"Invalid schedule expression: {every}") from e
            mode_desc = f"cron {every}"
        else:
            first_fire = datetime.now().astimezone()
            mode_desc = f"every {every}"

        local = first_fire.astimezone().isoformat(timespec="seconds")
        return f"Scheduled '{name}' ({mode_desc}), next run {local}"

    elif when:
        try:
            fire_at = datetime.fromisoformat(str(when))
        except ValueError as e:
            raise ValueError(f"Invalid datetime: {when}") from e
        local = fire_at.astimezone().isoformat(timespec="seconds")
        return f"Scheduled '{name}' for {local}"

    else:
        raise ValueError(
            f"Task '{name}' needs 'every' (cron/duration) or 'when' (ISO datetime)"
        )


# --- Scheduling tools ---


def register_scheduling_tools(docket: Any) -> None:
    """Register the list_scheduled tool."""

    @registry.tool(emoji=":alarm_clock:")
    async def list_scheduled(ctx: ToolContext) -> str:
        """List all scheduled and running tasks."""
        snap = await docket.snapshot()

        lines: list[str] = []

        for ex in snap.future:
            local = ex.when.astimezone().isoformat(timespec="seconds")
            prompt_file = ex.kwargs.get("prompt_file", "(inline prompt)")
            every = ex.kwargs.get("every", "")
            recur = f" (every {every})" if every else ""
            lines.append(f"  [{ex.key}] {local}{recur} — {prompt_file}")

        for ex in snap.running:
            prompt_file = ex.kwargs.get("prompt_file", "(inline prompt)")
            every = ex.kwargs.get("every", "")
            recur = f" (every {every})" if every else ""
            lines.append(f"  [{ex.key}] RUNNING{recur} — {prompt_file}")

        if not lines:
            return "No scheduled tasks"
        return f"{len(lines)} task(s):\n" + "\n".join(lines)
