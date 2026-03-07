"""Scheduling tool registration — schedule, schedule_every, cancel, list."""

from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter
from docket import Docket

from docketeer import environment, tasks
from docketeer.tasks import parse_every
from docketeer.tools import ToolContext, registry


def _reserved_task_keys(docket: Docket) -> set[str]:
    """Collect the keys of all automatic perpetual/cron tasks."""
    from docket.dependencies import Perpetual, get_single_dependency_parameter_of_type

    reserved: set[str] = set()
    for name, func in docket.tasks.items():
        dep = get_single_dependency_parameter_of_type(func, Perpetual)
        if dep is not None and dep.automatic:
            reserved.add(name)
    return reserved


def register_docket_tools(docket: Docket, tool_context: ToolContext) -> None:
    """Register scheduling tools that need the docket instance."""
    reserved_keys = _reserved_task_keys(docket)

    @registry.tool(emoji=":alarm_clock:")
    async def schedule(
        ctx: ToolContext,
        prompt_file: str,
        when: str,
        key: str = "",
        silent: bool = False,
        tier: str = "",
    ) -> str:
        """Schedule a nudge for yourself — a reminder, follow-up, or background work that
        fires at a future time. The time must be in the future — add the delay to the
        current time shown in your context. Scheduled nudges appear in list_scheduled
        and can be cancelled with cancel_task using their key.

        prompt_file: path to a file in your workspace containing the prompt (e.g. "tasks/remind-chris.md").
            This lets you write longer prompts, review and edit them, and discuss them with the user.
        when: ISO 8601 datetime in the future (e.g. 2026-02-07T15:00:00-05:00)
        key: unique identifier for cancellation/rescheduling (e.g. "remind-chris-dentist")
        silent: if true, work silently without sending a message (default: false)
        tier: intelligence tier — "smart", "balanced", or "fast" (default: chat tier)
        """
        try:
            fire_at = datetime.fromisoformat(when)
        except ValueError:
            return f"Error: invalid datetime format: {when}"

        if key and ":" in key:
            return "Error: task keys must not contain ':' (reserved for system tasks)"
        if key and key in reserved_keys:
            return f'Error: "{key}" is a built-in system task and cannot be overwritten'

        room_id = "" if silent else ctx.chat_room
        thread_id = "" if silent else ctx.thread_id

        if key:
            await docket.replace(tasks.nudge, when=fire_at, key=key)(
                prompt_file=prompt_file,
                room_id=room_id,
                thread_id=thread_id,
                tier=tier,
            )
        else:
            key = f"task-{fire_at.strftime('%Y%m%d-%H%M%S')}"
            await docket.add(tasks.nudge, when=fire_at, key=key)(
                prompt_file=prompt_file,
                room_id=room_id,
                thread_id=thread_id,
                tier=tier,
            )

        local = fire_at.astimezone().isoformat(timespec="seconds")
        mode = "silently" if silent else "in this room"
        return f'Scheduled "{key}" for {local} ({mode})'

    @registry.tool(emoji=":alarm_clock:")
    async def schedule_every(
        ctx: ToolContext,
        prompt_file: str,
        every: str,
        key: str,
        timezone: str = "",
        silent: bool = False,
        tier: str = "",
    ) -> str:
        """Schedule a recurring nudge for yourself on a fixed interval or cron schedule.
        Scheduled nudges appear in list_scheduled and can be cancelled with cancel_task
        using their key.

        prompt_file: path to a file in your workspace containing the prompt (e.g. "tasks/daily-checkin.md").
            This lets you write longer prompts, review and edit them, discuss them with the user,
            and modify the behavior of the recurring nudge without rescheduling it.
        every: ISO 8601 duration (PT30M, PT2H, P1D) or cron expression (0 9 * * 1-5, @daily)
        key: required — stable identifier for cancellation (e.g. "daily-standup")
        timezone: timezone for cron expressions (default: system timezone, ignored for durations)
        silent: if true, work silently without sending a message (default: false)
        tier: intelligence tier — "smart", "balanced", or "fast" (default: chat tier)
        """
        if ":" in key:
            return "Error: task keys must not contain ':' (reserved for system tasks)"
        if key in reserved_keys:
            return f'Error: "{key}" is a built-in system task and cannot be overwritten'

        duration = parse_every(every)

        if duration is None:
            if timezone:
                try:
                    tz = ZoneInfo(timezone)
                except (KeyError, ValueError):
                    return f"Error: invalid timezone: {timezone}"
            else:
                tz = environment.local_timezone()

            try:
                now = datetime.now(tz)
                first_fire = croniter(every, now).get_next(datetime)
            except (ValueError, KeyError):
                return f"Error: invalid schedule expression: {every}"

            mode_desc = f"cron {every}"
        else:
            first_fire = datetime.now().astimezone()
            mode_desc = f"every {every}"

        room_id = "" if silent else ctx.chat_room
        thread_id = "" if silent else ctx.thread_id

        await docket.replace(tasks.nudge_every, when=first_fire, key=key)(
            prompt_file=prompt_file,
            every=every,
            timezone=timezone,
            room_id=room_id,
            thread_id=thread_id,
            tier=tier,
        )

        local = first_fire.astimezone().isoformat(timespec="seconds")
        mode = "silently" if silent else "in this room"
        return f'Scheduled "{key}" ({mode_desc}, {mode}), first run {local}'

    @registry.tool(emoji=":alarm_clock:")
    async def cancel_task(ctx: ToolContext, key: str) -> str:
        """Cancel a scheduled task.

        key: the task key to cancel
        """
        await docket.cancel(key)
        return f'Cancelled "{key}"'

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
