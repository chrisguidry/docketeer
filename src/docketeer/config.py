"""Configuration from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    rocketchat_url: str
    rocketchat_username: str
    rocketchat_password: str
    anthropic_api_key: str
    workspace_path: Path
    claude_model: str = "claude-opus-4-6"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            rocketchat_url=os.environ["DOCKETEER_ROCKETCHAT_URL"],
            rocketchat_username=os.environ["DOCKETEER_ROCKETCHAT_USERNAME"],
            rocketchat_password=os.environ["DOCKETEER_ROCKETCHAT_PASSWORD"],
            anthropic_api_key=os.environ["DOCKETEER_ANTHROPIC_API_KEY"],
            workspace_path=Path(os.environ.get("DOCKETEER_WORKSPACE_PATH", "workspace")),
            claude_model=os.environ.get("DOCKETEER_CLAUDE_MODEL", "claude-opus-4-6"),
        )

    @property
    def rocketchat_ws_url(self) -> str:
        """Convert HTTP URL to websocket URL."""
        url = self.rocketchat_url.rstrip("/")
        if url.startswith("https://"):
            return url.replace("https://", "wss://") + "/websocket"
        elif url.startswith("http://"):
            return url.replace("http://", "ws://") + "/websocket"
        return url + "/websocket"
