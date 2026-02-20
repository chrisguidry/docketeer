"""Internal processing cycles — reverie and consolidation."""

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from docket.dependencies import Cron, Perpetual

from docketeer import environment
from docketeer.brain import CONSOLIDATION_MODEL, REVERIE_MODEL, Brain
from docketeer.brain.backend import BackendAuthError
from docketeer.dependencies import CurrentBrain, WorkspacePath
from docketeer.prompt import MessageContent

log = logging.getLogger(__name__)

_consecutive_failures: dict[str, int] = {}

REVERIE_INTERVAL = environment.get_timedelta("REVERIE_INTERVAL", timedelta(minutes=30))
CONSOLIDATION_CRON = environment.get_str("CONSOLIDATION_CRON", "0 3 * * *")

REVERIE_PROMPT = """\
[Internal cycle: reverie]

You are entering a reverie — a period of receptive internal processing.
Scan your raw material and transform it into understanding. Check on
promises, notice what needs attention, and tend to your workspace.

If something needs action directed at a person or room, use schedule()
to create a task for it. Not every reverie produces action — if nothing
needs doing, just move on.\
"""

CONSOLIDATION_PROMPT = """\
[Internal cycle: consolidation]

You are entering consolidation — your daily memory integration cycle.
This is where short-term observations become lasting understanding.
Review yesterday's experience, update what you know about the people
in your life, and look for patterns. Write a #reflection entry in
today's journal.\
"""


def _read_cycle_guidance(workspace: Path, section: str) -> str:
    """Read the agent's notes for a cycle from PRACTICE.md."""
    cycles_path = workspace / "PRACTICE.md"
    if not cycles_path.exists():
        return ""
    text = cycles_path.read_text()
    match = re.search(
        rf"^# {re.escape(section)}$\n(.*?)(?=^# |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def _build_cycle_prompt(base: str, workspace: Path, section: str) -> str:
    """Combine the immutable base prompt with optional agent guidance."""
    guidance = _read_cycle_guidance(workspace, section)
    if guidance:
        return f"{base}\n\nYour own notes for this cycle:\n\n{guidance}"
    return base


async def reverie(
    perpetual: Perpetual = Perpetual(every=REVERIE_INTERVAL, automatic=True),
    brain: Brain = CurrentBrain(),
    workspace: Path = WorkspacePath(),
) -> None:
    """Periodic receptive internal processing cycle."""
    prompt = _build_cycle_prompt(REVERIE_PROMPT, workspace, "Reverie")
    now = datetime.now().astimezone()
    content = MessageContent(username="system", timestamp=now, text=prompt)
    try:
        response = await brain.process("__tasks__", content, model=REVERIE_MODEL)
    except BackendAuthError:
        raise
    except Exception:
        _consecutive_failures["reverie"] = _consecutive_failures.get("reverie", 0) + 1
        level = (
            logging.ERROR if _consecutive_failures["reverie"] >= 3 else logging.WARNING
        )
        log.log(
            level,
            "Error during reverie cycle (attempt %d)",
            _consecutive_failures["reverie"],
            exc_info=True,
        )
        return
    _consecutive_failures.pop("reverie", None)
    if response.text:
        log.info("Reverie: %s", response.text)


async def consolidation(
    cron: Cron = Cron(
        CONSOLIDATION_CRON, automatic=True, tz=environment.local_timezone()
    ),
    brain: Brain = CurrentBrain(),
    workspace: Path = WorkspacePath(),
) -> None:
    """Daily memory integration and reflection cycle."""
    prompt = _build_cycle_prompt(CONSOLIDATION_PROMPT, workspace, "Consolidation")
    now = datetime.now().astimezone()
    content = MessageContent(username="system", timestamp=now, text=prompt)
    try:
        response = await brain.process("__tasks__", content, model=CONSOLIDATION_MODEL)
    except BackendAuthError:
        raise
    except Exception:
        _consecutive_failures["consolidation"] = (
            _consecutive_failures.get("consolidation", 0) + 1
        )
        level = (
            logging.ERROR
            if _consecutive_failures["consolidation"] >= 3
            else logging.WARNING
        )
        log.log(
            level,
            "Error during consolidation cycle (attempt %d)",
            _consecutive_failures["consolidation"],
            exc_info=True,
        )
        return
    _consecutive_failures.pop("consolidation", None)
    if response.text:
        log.info("Consolidation: %s", response.text)
