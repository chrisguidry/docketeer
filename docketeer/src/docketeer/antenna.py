"""Realtime event feeds — the antenna system.

Bands are persistent streaming connections (SSE, WebSocket, etc.) that
produce Signals.  Tunings tie a band + topic + filters to a line of
thinking.  The Antenna owns bands and tunings and routes signals to lines.

Also contains the AntennaHook (workspace hook for tunings/ directory) and
the list_bands tool.
"""

import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol, cast

from docketeer.hooks import HookResult, parse_frontmatter
from docketeer.plugins import discover_all
from docketeer.prompt import BrainResponse, MessageContent, SystemBlock
from docketeer.tools import ToolContext, registry
from docketeer.vault import Vault

log = logging.getLogger(__name__)


class ProcessFn(Protocol):
    """The contract for delivering messages to a line of thinking."""

    async def __call__(
        self,
        line: str,
        content: MessageContent,
        *,
        tier: str = "",
        system_context: list[SystemBlock] | None = None,
    ) -> BrainResponse: ...


# --- Data types ---


@dataclass(frozen=True)
class Signal:
    """A single event from a band."""

    band: str
    signal_id: str
    timestamp: datetime
    topic: str
    payload: dict[str, Any]
    summary: str = ""


FilterOp = Literal["eq", "ne", "contains", "icontains", "startswith", "exists"]


@dataclass(frozen=True)
class SignalFilter:
    """A predicate evaluated against signal fields."""

    path: str  # dot-path: "payload.action", "topic"
    op: FilterOp
    value: str = ""


@dataclass
class Tuning:
    """Ties a band + topic + filters to a line."""

    name: str
    band: str
    topic: str
    filters: list[SignalFilter] = field(default_factory=list)
    line: str = ""  # defaults to tuning name
    secrets: dict[str, str] | None = None
    retention_days: int = 7

    @property
    def target_line(self) -> str:
        return self.line or self.name


# --- Filter evaluation ---


def _resolve_path(obj: Any, path: str) -> Any:
    """Walk a dot-separated path into a nested dict/object."""
    for part in path.split("."):
        if isinstance(obj, dict):
            if part not in obj:
                return _MISSING
            obj = obj[part]
        elif hasattr(obj, part):
            obj = getattr(obj, part)
        else:
            return _MISSING
    return obj


_MISSING = object()


def evaluate_filter(f: SignalFilter, signal: Signal) -> bool:
    """Evaluate a single filter against a signal."""
    value = _resolve_path(signal, f.path)

    if f.op == "exists":
        return value is not _MISSING

    if value is _MISSING:
        return False

    str_value = str(value)

    match f.op:
        case "eq":
            return str_value == f.value
        case "ne":
            return str_value != f.value
        case "contains":
            return f.value in str_value
        case "icontains":
            return f.value.lower() in str_value.lower()
        case "startswith":
            return str_value.startswith(f.value)
        case _:
            log.warning("Unknown filter op: %s", f.op)
            return False


def passes_filters(filters: list[SignalFilter], signal: Signal) -> bool:
    """Check whether a signal passes all filters."""
    return all(evaluate_filter(f, signal) for f in filters)


# --- Band ABC ---


class Band(ABC):
    """A persistent streaming connection that produces signals."""

    name: str
    description: str = ""

    @abstractmethod
    async def __aenter__(self) -> "Band": ...

    @abstractmethod
    async def __aexit__(self, *exc: object) -> None: ...

    @abstractmethod
    def listen(
        self,
        topic: str,
        filters: list[SignalFilter],
        last_signal_id: str = "",
        secrets: dict[str, str] | None = None,
    ) -> AsyncGenerator[Signal, None]:
        """Yield signals matching the topic and remote-compatible filters."""
        ...  # pragma: no cover

    def remote_filter_hints(self, filters: list[SignalFilter]) -> list[SignalFilter]:
        """Return filters the band can push to the remote for server-side filtering."""
        return []


# --- Band discovery ---


def discover_bands() -> dict[str, Band]:
    """Load all installed band plugins via the docketeer.bands entry point."""
    bands: dict[str, Band] = {}
    for factory in discover_all("docketeer.bands"):
        band = factory()
        bands[band.name] = band
    return bands


class Antenna:
    """Orchestrator — owns bands, tunings, and signal routing tasks."""

    def __init__(
        self,
        process_fn: ProcessFn,
        workspace: Path,
        vault: Vault | None = None,
    ) -> None:
        self._process_fn = process_fn
        self._workspace = workspace
        self._vault = vault
        self._bands: dict[str, Band] = {}
        self._tunings: dict[str, Tuning] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def __aenter__(self) -> "Antenna":
        self._bands = discover_bands()
        for band in self._bands.values():
            await band.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        for task in self._tasks.values():
            task.cancel()
        for task in self._tasks.values():
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()

        for band in self._bands.values():
            await band.__aexit__(None, None, None)

    def _start_task(self, tuning: Tuning) -> None:
        band = self._bands[tuning.band]

        if tuning.secrets and not self._vault:
            log.warning(
                "Tuning '%s' requires secrets but no vault is available, skipping",
                tuning.name,
            )
            return

        self._tasks[tuning.name] = asyncio.create_task(
            self._resolve_and_run(band, tuning),
            name=f"antenna:{tuning.name}",
        )

    async def _resolve_and_run(self, band: Band, tuning: Tuning) -> None:
        from docketeer.signal_loop import run_tuning

        resolved: dict[str, str] | None = None
        if tuning.secrets and self._vault:
            resolved = {}
            for key, vault_path in tuning.secrets.items():
                resolved[key] = await self._vault.resolve(vault_path)

        await run_tuning(
            band,
            tuning,
            self._process_fn,
            self._workspace,
            secrets=resolved,
        )

    async def _stop_task(self, name: str) -> None:
        task = self._tasks.pop(name, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def tune(self, tuning: Tuning) -> None:
        """Add or replace a tuning. Starts listening immediately."""
        if tuning.band not in self._bands:
            raise ValueError(
                f"Unknown band '{tuning.band}'. Available: {sorted(self._bands)}"
            )

        await self._stop_task(tuning.name)
        self._tunings[tuning.name] = tuning
        self._start_task(tuning)

    async def detune(self, name: str) -> None:
        """Remove a tuning and stop its task."""
        if name not in self._tunings:
            raise KeyError(f"No tuning named '{name}'")

        await self._stop_task(name)
        del self._tunings[name]

    def list_tunings(self) -> list[Tuning]:
        """Return all active tunings."""
        return list(self._tunings.values())

    def list_bands(self) -> list[Band]:
        """Return all discovered bands, sorted by name."""
        return sorted(self._bands.values(), key=lambda b: b.name)


# --- Antenna hook ---


def _parse_filters(raw_filters: list) -> list[SignalFilter]:
    """Convert frontmatter filter dicts to SignalFilter objects."""
    filters: list[SignalFilter] = []
    for f in raw_filters:
        if not isinstance(f, dict):
            continue
        path = f.get("field") or f.get("path", "")
        op = f.get("op", "eq")
        value = f.get("value", "")
        filters.append(
            SignalFilter(path=str(path), op=cast(FilterOp, op), value=str(value))
        )
    return filters


def _parse_tuning(name: str, meta: dict) -> Tuning:
    """Build a Tuning from parsed frontmatter metadata."""
    band = meta.get("band")
    topic = meta.get("topic")

    if not band or not topic:
        raise ValueError(f"Tuning '{name}' requires 'band' and 'topic' in frontmatter")

    return Tuning(
        name=name,
        band=str(band),
        topic=str(topic),
        filters=_parse_filters(meta.get("filters", [])),
        line=str(meta.get("line", "")),
        secrets=meta.get("secrets"),
        retention_days=int(meta.get("retention_days", 7)),
    )


class AntennaHook:
    """Workspace hook for the tunings/ directory."""

    prefix = PurePosixPath("tunings")

    def __init__(self) -> None:
        self._antenna: Antenna | None = None

    def set_antenna(self, antenna: Antenna) -> None:
        self._antenna = antenna

    @property
    def _antenna_required(self) -> Antenna:
        if self._antenna is None:
            raise RuntimeError("AntennaHook not wired to an Antenna")
        return self._antenna

    def _is_tuning_file(self, path: PurePosixPath) -> bool:
        """Check if this is a top-level .md file in tunings/."""
        return path.name.endswith(".md") and len(path.parts) <= 2

    async def validate(self, path: PurePosixPath, content: str) -> HookResult | None:
        """Parse and validate tuning frontmatter."""
        if not self._is_tuning_file(path):
            return None

        meta, _ = parse_frontmatter(content)
        if not meta:
            raise ValueError(
                f"Tuning file {path} needs YAML frontmatter with 'band' and 'topic'"
            )

        name = path.stem
        tuning = _parse_tuning(name, meta)

        # Validate the band exists
        antenna = self._antenna_required
        if tuning.band not in antenna._bands:
            raise ValueError(
                f"Unknown band '{tuning.band}'. Available: {sorted(antenna._bands)}"
            )

        target = tuning.line or name
        msg = f"Tuned '{name}' on band '{tuning.band}', delivering to line '{target}'"
        return HookResult(msg)

    async def commit(self, path: PurePosixPath, content: str) -> None:
        """Activate the tuning via the antenna."""
        if not self._is_tuning_file(path):
            return

        meta, _ = parse_frontmatter(content)
        name = path.stem
        tuning = _parse_tuning(name, meta)

        antenna = self._antenna_required
        await antenna.tune(tuning)
        log.info("Tuned '%s' on band '%s'", name, tuning.band)

    async def on_delete(self, path: PurePosixPath) -> str | None:
        """Stop the tuning."""
        if not self._is_tuning_file(path):
            return None

        name = path.stem
        antenna = self._antenna_required

        try:
            await antenna.detune(name)
        except KeyError:
            return f"No tuning named '{name}' was active"
        log.info("Detuned '%s'", name)
        return f"Detuned '{name}'"

    async def scan(self, workspace: Path) -> None:
        """Reconcile tunings/ files with running antenna tasks."""
        tunings_dir = workspace / "tunings"
        if not tunings_dir.is_dir():
            return

        for md_file in sorted(tunings_dir.glob("*.md")):
            content = md_file.read_text()
            meta, _ = parse_frontmatter(content)
            if not meta:
                continue

            name = md_file.stem
            band = meta.get("band")
            topic = meta.get("topic")
            if not band or not topic:
                continue

            tuning = _parse_tuning(name, meta)
            antenna = self._antenna_required
            try:
                await antenna.tune(tuning)
            except ValueError:
                log.warning("Scan: skipping tuning '%s'", name, exc_info=True)


# --- Antenna tools ---


def register_antenna_tools(antenna: Antenna) -> None:
    """Register the list_bands tool."""

    @registry.tool(emoji=":satellite:")
    async def list_bands(ctx: ToolContext) -> str:
        """Show available bands — the event sources you can tune into
        (e.g. wicket for SSE webhooks, atproto for Bluesky events).
        Each band describes how topic, filters, and secret map to that platform."""
        bands = antenna.list_bands()
        if not bands:
            return "No bands available."

        sections: list[str] = []
        for band in bands:
            header = f"  [{band.name}]"
            if band.description:
                header += f"\n{_indent(band.description, 4)}"
            sections.append(header)
        return f"{len(bands)} band(s):\n\n" + "\n\n".join(sections)


def _indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(f"{prefix}{line}" for line in text.strip().splitlines())
