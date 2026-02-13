"""Tests for cycle configuration via module-level constants."""

import logging
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from docket.dependencies import Cron, Perpetual

from docketeer import cycles
from docketeer.cycles import _read_cycle_guidance


def test_reverie_default_uses_module_interval():
    defaults = cycles.reverie.__defaults__
    assert defaults is not None
    assert isinstance(defaults[0], Perpetual)
    assert defaults[0].every == cycles.REVERIE_INTERVAL


def test_consolidation_default_uses_module_cron():
    defaults = cycles.consolidation.__defaults__
    assert defaults is not None
    assert isinstance(defaults[0], Cron)
    assert defaults[0].expression == cycles.CONSOLIDATION_CRON


def test_reverie_interval_is_timedelta():
    assert isinstance(cycles.REVERIE_INTERVAL, timedelta)


def test_consolidation_cron_is_string():
    assert isinstance(cycles.CONSOLIDATION_CRON, str)


# --- _read_cycle_guidance regex parsing ---


def test_read_cycle_guidance_basic(tmp_path: Path):
    (tmp_path / "PRACTICE.md").write_text(
        "# Reverie\nScan for patterns.\n\n# Consolidation\nReflect on the day.\n"
    )
    assert _read_cycle_guidance(tmp_path, "Reverie") == "Scan for patterns."
    assert _read_cycle_guidance(tmp_path, "Consolidation") == "Reflect on the day."


def test_read_cycle_guidance_section_at_end(tmp_path: Path):
    (tmp_path / "PRACTICE.md").write_text("# Reverie\nEnd of file content.\n")
    assert _read_cycle_guidance(tmp_path, "Reverie") == "End of file content."


def test_read_cycle_guidance_ignores_subheadings(tmp_path: Path):
    (tmp_path / "PRACTICE.md").write_text(
        "# Reverie\nIntro.\n## Details\nMore info.\n\n# Consolidation\nDone.\n"
    )
    result = _read_cycle_guidance(tmp_path, "Reverie")
    assert "## Details" in result
    assert "More info." in result


def test_read_cycle_guidance_missing_section(tmp_path: Path):
    (tmp_path / "PRACTICE.md").write_text("# Other\nStuff.\n")
    assert _read_cycle_guidance(tmp_path, "Reverie") == ""


def test_read_cycle_guidance_missing_file(tmp_path: Path):
    assert _read_cycle_guidance(tmp_path, "Reverie") == ""


# --- consecutive failure tracking ---


@pytest.fixture(autouse=True)
def _reset_failure_counters() -> Iterator[None]:
    """Reset module-level failure counters between tests."""
    cycles._consecutive_failures.clear()
    yield
    cycles._consecutive_failures.clear()


async def test_reverie_consecutive_failures_escalate(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    brain = AsyncMock()
    brain.process.side_effect = RuntimeError("boom")

    for i in range(4):
        with caplog.at_level(logging.DEBUG):
            caplog.clear()
            await cycles.reverie(brain=brain, workspace=tmp_path)
            if i < 2:
                assert any(r.levelno == logging.WARNING for r in caplog.records)
            else:
                assert any(r.levelno == logging.ERROR for r in caplog.records)

    assert cycles._consecutive_failures["reverie"] == 4


async def test_reverie_success_resets_counter(tmp_path: Path):
    brain = AsyncMock()
    brain.process.side_effect = RuntimeError("boom")
    await cycles.reverie(brain=brain, workspace=tmp_path)
    assert cycles._consecutive_failures.get("reverie") == 1

    brain.process.side_effect = None
    brain.process.return_value = AsyncMock(text="ok")
    await cycles.reverie(brain=brain, workspace=tmp_path)
    assert "reverie" not in cycles._consecutive_failures
