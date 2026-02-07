"""Internal processing cycles — reverie and consolidation."""

import logging
from datetime import datetime, timedelta
from pathlib import Path

from docket.dependencies import Cron, Perpetual

from docketeer import environment
from docketeer.prompt import MessageContent

log = logging.getLogger(__name__)

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
    """Read the agent's notes for a cycle from CYCLES.md."""
    cycles_path = workspace / "CYCLES.md"
    if not cycles_path.exists():
        return ""
    text = cycles_path.read_text()
    marker = f"# {section}"
    start = text.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    end = text.find("\n# ", start)
    return text[start:end].strip() if end != -1 else text[start:].strip()


def _build_cycle_prompt(base: str, workspace: Path, section: str) -> str:
    """Combine the immutable base prompt with optional agent guidance."""
    guidance = _read_cycle_guidance(workspace, section)
    if guidance:
        return f"{base}\n\nYour own notes for this cycle:\n\n{guidance}"
    return base


async def reverie(
    perpetual: Perpetual = Perpetual(every=REVERIE_INTERVAL, automatic=True),
) -> None:
    """Periodic receptive internal processing cycle."""
    from docketeer.tasks import get_brain

    brain = get_brain()
    prompt = _build_cycle_prompt(REVERIE_PROMPT, brain._workspace, "Reverie")
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    content = MessageContent(username="system", timestamp=now, text=prompt)
    response = await brain.process("__tasks__", content)
    if response.text:
        log.info("Reverie: %s", response.text)


async def consolidation(
    cron: Cron = Cron(CONSOLIDATION_CRON, automatic=True),
) -> None:
    """Daily memory integration and reflection cycle."""
    from docketeer.tasks import get_brain

    brain = get_brain()
    prompt = _build_cycle_prompt(
        CONSOLIDATION_PROMPT, brain._workspace, "Consolidation"
    )
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    content = MessageContent(username="system", timestamp=now, text=prompt)
    response = await brain.process("__tasks__", content)
    if response.text:
        log.info("Consolidation: %s", response.text)
