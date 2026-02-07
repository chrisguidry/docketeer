"""Tests for cycle configuration via module-level constants."""

from datetime import timedelta

from docket.dependencies import Cron, Perpetual

from docketeer import cycles


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
