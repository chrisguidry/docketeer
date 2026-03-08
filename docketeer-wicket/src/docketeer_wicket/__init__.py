"""Wicket SSE band plugin for Docketeer."""

from docketeer_wicket.band import WicketBand


def create_band() -> WicketBand:
    return WicketBand()
