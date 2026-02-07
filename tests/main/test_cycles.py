"""Tests for cycle configuration in main."""

from datetime import timedelta

from docket.dependencies import Cron, Perpetual

from docketeer import cycles
from docketeer.config import Config
from docketeer.main import _configure_cycles


def test_configure_cycles_patches_reverie(config: Config):
    config.reverie_minutes = 30
    _configure_cycles(config)
    defaults = cycles.reverie.__defaults__
    assert defaults is not None
    assert isinstance(defaults[0], Perpetual)
    assert defaults[0].every == timedelta(minutes=30)


def test_configure_cycles_patches_consolidation(config: Config):
    config.consolidation_cron = "0 8 * * *"
    _configure_cycles(config)
    defaults = cycles.consolidation.__defaults__
    assert defaults is not None
    assert isinstance(defaults[0], Cron)
    assert defaults[0].expression == "0 8 * * *"


def test_configure_cycles_skips_when_none(config: Config):
    original_reverie = cycles.reverie.__defaults__
    original_consolidation = cycles.consolidation.__defaults__
    config.reverie_minutes = None
    config.consolidation_cron = None
    _configure_cycles(config)
    assert cycles.reverie.__defaults__ is original_reverie
    assert cycles.consolidation.__defaults__ is original_consolidation
