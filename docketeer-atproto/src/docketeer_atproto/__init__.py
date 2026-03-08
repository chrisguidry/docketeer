"""ATProto Jetstream band plugin for Docketeer."""

from docketeer_atproto.band import JetstreamBand


def create_band() -> JetstreamBand:
    return JetstreamBand()
