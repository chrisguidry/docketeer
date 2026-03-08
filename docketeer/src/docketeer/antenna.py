"""Realtime event feeds — the antenna system.

Bands are persistent streaming connections (SSE, WebSocket, etc.) that
produce Signals.  Tunings tie a band + topic + filters to a line of
thinking.  The Antenna owns bands and tunings and routes signals to lines.
"""

import asyncio
import contextlib
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from docketeer.plugins import discover_all
from docketeer.prompt import BrainResponse, MessageContent, SystemBlock

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


@dataclass(frozen=True)
class SignalFilter:
    """A predicate evaluated against signal fields."""

    path: str  # dot-path: "payload.action", "topic"
    op: str  # "eq", "ne", "contains", "startswith", "exists"
    value: str = ""


@dataclass
class Tuning:
    """Ties a band + topic + filters to a line."""

    name: str
    band: str
    topic: str
    filters: list[SignalFilter] = field(default_factory=list)
    line: str = ""  # defaults to tuning name
    batch_window: float = 5.0
    max_batch: int = 10

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


# --- Tuning persistence ---


def load_tunings(data_dir: Path) -> list[Tuning]:
    """Load tunings from the data directory."""
    path = data_dir / "tunings.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [_tuning_from_dict(d) for d in data]


def save_tunings(data_dir: Path, tunings: list[Tuning]) -> None:
    """Save tunings to the data directory."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "tunings.json"
    data = [_tuning_to_dict(t) for t in tunings]
    path.write_text(json.dumps(data, indent=2) + "\n")


def _tuning_to_dict(t: Tuning) -> dict[str, Any]:
    return {
        "name": t.name,
        "band": t.band,
        "topic": t.topic,
        "filters": [{"path": f.path, "op": f.op, "value": f.value} for f in t.filters],
        "line": t.line,
        "batch_window": t.batch_window,
        "max_batch": t.max_batch,
    }


class Antenna:
    """Orchestrator — owns bands, tunings, and signal routing tasks."""

    def __init__(
        self,
        process_fn: ProcessFn,
        data_dir: Path,
        workspace: Path,
    ) -> None:
        self._process_fn = process_fn
        self._data_dir = data_dir
        self._workspace = workspace
        self._bands: dict[str, Band] = {}
        self._tunings: dict[str, Tuning] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def __aenter__(self) -> "Antenna":
        self._bands = discover_bands()
        for band in self._bands.values():
            await band.__aenter__()

        for tuning in load_tunings(self._data_dir):
            self._tunings[tuning.name] = tuning
            self._start_task(tuning)

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
        from docketeer.signal_loop import run_tuning

        band = self._bands.get(tuning.band)
        if band is None:
            log.warning(
                "Tuning '%s' references unknown band '%s', skipping",
                tuning.name,
                tuning.band,
            )
            return

        self._tasks[tuning.name] = asyncio.create_task(
            run_tuning(band, tuning, self._process_fn, self._workspace),
            name=f"antenna:{tuning.name}",
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
        save_tunings(self._data_dir, list(self._tunings.values()))

    async def detune(self, name: str) -> None:
        """Remove a tuning and stop its task."""
        if name not in self._tunings:
            raise KeyError(f"No tuning named '{name}'")

        await self._stop_task(name)
        del self._tunings[name]
        save_tunings(self._data_dir, list(self._tunings.values()))

    def list_tunings(self) -> list[Tuning]:
        """Return all active tunings."""
        return list(self._tunings.values())

    def list_bands(self) -> list[str]:
        """Return names of all discovered bands."""
        return sorted(self._bands)


def _tuning_from_dict(d: dict[str, Any]) -> Tuning:
    return Tuning(
        name=d["name"],
        band=d["band"],
        topic=d["topic"],
        filters=[SignalFilter(**f) for f in d.get("filters", [])],
        line=d.get("line", ""),
        batch_window=d.get("batch_window", 5.0),
        max_batch=d.get("max_batch", 10),
    )
