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
from typing import Any, Literal, Protocol

from docketeer.plugins import discover_all
from docketeer.prompt import BrainResponse, MessageContent, SystemBlock
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
    secret: str | None = None

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
        secret: str | None = None,
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


def _tunings_dir(data_dir: Path) -> Path:
    return data_dir / "tunings"


def load_tunings(data_dir: Path) -> list[Tuning]:
    """Load all tunings from individual files in the tunings directory."""
    tunings_path = _tunings_dir(data_dir)
    if not tunings_path.is_dir():
        return []
    tunings: list[Tuning] = []
    for path in sorted(tunings_path.glob("*.json")):
        data = json.loads(path.read_text())
        tunings.append(_tuning_from_dict(data))
    return tunings


def save_tuning(data_dir: Path, tuning: Tuning) -> None:
    """Save a single tuning to its own file."""
    tunings_path = _tunings_dir(data_dir)
    tunings_path.mkdir(parents=True, exist_ok=True)
    path = tunings_path / f"{tuning.name}.json"
    path.write_text(json.dumps(_tuning_to_dict(tuning), indent=2) + "\n")


def delete_tuning(data_dir: Path, name: str) -> None:
    """Delete a tuning file."""
    path = _tunings_dir(data_dir) / f"{name}.json"
    path.unlink(missing_ok=True)


def _tuning_to_dict(t: Tuning) -> dict[str, Any]:
    return {
        "name": t.name,
        "band": t.band,
        "topic": t.topic,
        "filters": [{"path": f.path, "op": f.op, "value": f.value} for f in t.filters],
        "line": t.line,
        "secret": t.secret,
    }


class Antenna:
    """Orchestrator — owns bands, tunings, and signal routing tasks."""

    def __init__(
        self,
        process_fn: ProcessFn,
        data_dir: Path,
        workspace: Path,
        vault: Vault | None = None,
    ) -> None:
        self._process_fn = process_fn
        self._data_dir = data_dir
        self._workspace = workspace
        self._vault = vault
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
        band = self._bands.get(tuning.band)
        if band is None:
            log.warning(
                "Tuning '%s' references unknown band '%s', skipping",
                tuning.name,
                tuning.band,
            )
            return

        if tuning.secret is not None and not self._vault:
            log.warning(
                "Tuning '%s' requires secret '%s' but no vault is available, skipping",
                tuning.name,
                tuning.secret,
            )
            return

        self._tasks[tuning.name] = asyncio.create_task(
            self._resolve_and_run(band, tuning),
            name=f"antenna:{tuning.name}",
        )

    async def _resolve_and_run(self, band: Band, tuning: Tuning) -> None:
        from docketeer.signal_loop import run_tuning

        secret: str | None = None
        if tuning.secret is not None and self._vault:
            secret = await self._vault.resolve(tuning.secret)

        await run_tuning(
            band,
            tuning,
            self._process_fn,
            self._workspace,
            secret=secret,
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
        save_tuning(self._data_dir, tuning)

    async def detune(self, name: str) -> None:
        """Remove a tuning and stop its task."""
        if name not in self._tunings:
            raise KeyError(f"No tuning named '{name}'")

        await self._stop_task(name)
        del self._tunings[name]
        delete_tuning(self._data_dir, name)

    def list_tunings(self) -> list[Tuning]:
        """Return all active tunings."""
        return list(self._tunings.values())

    def list_bands(self) -> list[Band]:
        """Return all discovered bands, sorted by name."""
        return sorted(self._bands.values(), key=lambda b: b.name)


def _tuning_from_dict(d: dict[str, Any]) -> Tuning:
    return Tuning(
        name=d["name"],
        band=d["band"],
        topic=d["topic"],
        filters=[SignalFilter(**f) for f in d.get("filters", [])],
        line=d.get("line", ""),
        secret=d.get("secret"),
    )
