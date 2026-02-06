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
    data_dir: Path
    brave_api_key: str = ""
    claude_model: str = "claude-opus-4-6"
    docket_url: str = "redis://localhost:6379/0"
    docket_name: str = "docketeer"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            rocketchat_url=os.environ["DOCKETEER_ROCKETCHAT_URL"],
            rocketchat_username=os.environ["DOCKETEER_ROCKETCHAT_USERNAME"],
            rocketchat_password=os.environ["DOCKETEER_ROCKETCHAT_PASSWORD"],
            anthropic_api_key=os.environ["DOCKETEER_ANTHROPIC_API_KEY"],
            data_dir=Path(
                os.environ.get("DOCKETEER_DATA_DIR", "~/.docketeer")
            ).expanduser(),
            brave_api_key=os.environ.get("DOCKETEER_BRAVE_API_KEY", ""),
            claude_model=os.environ.get("DOCKETEER_CLAUDE_MODEL", "claude-opus-4-6"),
            docket_url=os.environ.get("DOCKETEER_DOCKET_URL", "redis://localhost:6379/0"),
            docket_name=os.environ.get("DOCKETEER_DOCKET_NAME", "docketeer"),
        )

    @property
    def workspace_path(self) -> Path:
        return self.data_dir / "memory"

    @property
    def audit_path(self) -> Path:
        return self.data_dir / "audit"

    @property
    def rocketchat_ws_url(self) -> str:
        """Convert HTTP URL to websocket URL."""
        url = self.rocketchat_url.rstrip("/")
        if url.startswith("https://"):
            return url.replace("https://", "wss://") + "/websocket"
        elif url.startswith("http://"):
            return url.replace("http://", "ws://") + "/websocket"
        return url + "/websocket"
