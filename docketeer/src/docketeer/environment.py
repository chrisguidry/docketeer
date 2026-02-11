"""Typed environment variable helpers with DOCKETEER_ prefix."""

import os
import re
from datetime import timedelta
from pathlib import Path
from typing import overload

_PREFIX = "DOCKETEER_"
_MISSING = object()


@overload
def get_str(name: str) -> str: ...


@overload
def get_str(name: str, default: str) -> str: ...


def get_str(name: str, default: object = _MISSING) -> str:
    """Read DOCKETEER_{name} as a string.

    With no default, raises KeyError if the variable is unset.
    With a default, returns the default when unset.
    """
    key = f"{_PREFIX}{name}"
    if default is _MISSING:
        return os.environ[key]
    return os.environ.get(key, default)  # type: ignore[arg-type]


def get_int(name: str, default: int) -> int:
    """Read DOCKETEER_{name} as an integer."""
    raw = os.environ.get(f"{_PREFIX}{name}")
    if raw is None:
        return default
    return int(raw)


def get_path(name: str, default: str) -> Path:
    """Read DOCKETEER_{name} as an expanded Path."""
    raw = os.environ.get(f"{_PREFIX}{name}", default)
    return Path(raw).expanduser()


def get_timedelta(name: str, default: timedelta) -> timedelta:
    """Read DOCKETEER_{name} as a timedelta.

    Accepts either integer seconds (e.g. "1800") or an ISO 8601 duration
    string (e.g. "PT30M", "P1DT2H", "PT1H30M45S").
    """
    raw = os.environ.get(f"{_PREFIX}{name}")
    if raw is None:
        return default
    if raw.startswith("P"):
        return _parse_iso8601_duration(raw)
    return timedelta(seconds=int(raw))


_ISO_DURATION = re.compile(
    r"^P"
    r"(?:(\d+)D)?"
    r"(?:T"
    r"(?:(\d+)H)?"
    r"(?:(\d+)M)?"
    r"(?:(\d+)S)?"
    r")?$"
)


def _parse_iso8601_duration(value: str) -> timedelta:
    """Parse a subset of ISO 8601 durations into a timedelta."""
    m = _ISO_DURATION.match(value)
    if not m:
        raise ValueError(f"Cannot parse ISO 8601 duration: {value}")
    days = int(m.group(1) or 0)
    hours = int(m.group(2) or 0)
    minutes = int(m.group(3) or 0)
    seconds = int(m.group(4) or 0)
    return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


DATA_DIR = get_path("DATA_DIR", "~/.docketeer")
WORKSPACE_PATH = DATA_DIR / "memory"
AUDIT_PATH = DATA_DIR / "audit"
USAGE_PATH = DATA_DIR / "token-usage"
