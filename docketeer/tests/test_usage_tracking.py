"""Tests for token usage recording."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from docketeer.audit import record_usage
from docketeer.brain.backend import Usage


@patch("docketeer.audit.datetime")
def test_record_usage_creates_daily_file(mock_dt: MagicMock, tmp_path: Path):
    mock_dt.now.return_value = datetime(2026, 2, 10, 22, 15, 0, tzinfo=UTC)
    usage_dir = tmp_path / "token-usage"

    record_usage(
        usage_dir,
        "claude-haiku-4-5-20251001",
        Usage(input_tokens=100, output_tokens=50),
    )

    daily_file = usage_dir / "2026-02-10.jsonl"
    assert daily_file.exists()


@patch("docketeer.audit.datetime")
def test_record_usage_appends(mock_dt: MagicMock, tmp_path: Path):
    mock_dt.now.return_value = datetime(2026, 2, 10, 22, 15, 0, tzinfo=UTC)
    usage_dir = tmp_path / "token-usage"

    record_usage(
        usage_dir,
        "claude-haiku-4-5-20251001",
        Usage(input_tokens=100, output_tokens=50),
    )
    record_usage(
        usage_dir,
        "claude-sonnet-4-5-20250929",
        Usage(input_tokens=200, output_tokens=50),
    )

    daily_file = usage_dir / "2026-02-10.jsonl"
    lines = daily_file.read_text().strip().splitlines()
    assert len(lines) == 2


@patch("docketeer.audit.datetime")
def test_record_usage_fields(mock_dt: MagicMock, tmp_path: Path):
    mock_dt.now.return_value = datetime(2026, 2, 10, 22, 15, 0, tzinfo=UTC)
    usage_dir = tmp_path / "token-usage"

    record_usage(
        usage_dir,
        "claude-haiku-4-5-20251001",
        Usage(
            input_tokens=50,
            output_tokens=393,
            cache_read_input_tokens=188_086,
            cache_creation_input_tokens=0,
        ),
    )

    daily_file = usage_dir / "2026-02-10.jsonl"
    record = json.loads(daily_file.read_text().strip())
    assert record["ts"] == "2026-02-10T22:15:00+00:00"
    assert record["model"] == "claude-haiku-4-5-20251001"
    assert record["input_tokens"] == 50
    assert record["output_tokens"] == 393
    assert record["cache_read_input_tokens"] == 188_086
    assert record["cache_creation_input_tokens"] == 0


@patch("docketeer.audit.datetime")
def test_record_usage_cache_fields_optional(mock_dt: MagicMock, tmp_path: Path):
    mock_dt.now.return_value = datetime(2026, 2, 10, 22, 15, 0, tzinfo=UTC)
    usage_dir = tmp_path / "token-usage"

    record_usage(
        usage_dir,
        "claude-haiku-4-5-20251001",
        Usage(input_tokens=100, output_tokens=50),
    )

    daily_file = usage_dir / "2026-02-10.jsonl"
    record = json.loads(daily_file.read_text().strip())
    assert record["input_tokens"] == 100
    assert record["output_tokens"] == 50
    assert record["cache_read_input_tokens"] == 0
    assert record["cache_creation_input_tokens"] == 0
