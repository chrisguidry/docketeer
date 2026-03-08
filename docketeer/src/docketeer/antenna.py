"""Realtime event feeds — the antenna system.

Bands are persistent streaming connections (SSE, WebSocket, etc.) that
produce Signals.  Tunings tie a band + topic + filters to a line of
thinking.  The Antenna owns bands and tunings and routes signals to lines.
"""

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from docketeer.plugins import discover_all

log = logging.getLogger(__name__)


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
