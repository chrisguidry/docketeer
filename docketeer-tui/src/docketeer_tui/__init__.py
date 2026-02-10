"""Terminal chat backend for Docketeer."""

from docketeer_tui.client import TUIClient


def create_client() -> TUIClient:
    """Create and return a TUIClient instance."""
    return TUIClient()
