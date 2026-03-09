"""IMAP IDLE band plugin for Docketeer."""

from docketeer_imap.band import ImapBand


def create_band() -> ImapBand:
    return ImapBand()
