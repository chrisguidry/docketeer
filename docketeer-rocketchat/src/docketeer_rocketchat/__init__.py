"""Rocket Chat backend for Docketeer."""

from docketeer.chat import ChatClient
from docketeer.tools import ToolContext, _safe_path, registry
from docketeer_rocketchat.client import RocketChatClient


def create_client() -> RocketChatClient:
    """Create and return a RocketChatClient instance."""
    return RocketChatClient()


def register_tools(client: ChatClient, tool_context: ToolContext) -> None:
    """Register Rocket Chat-specific tools (send_file)."""

    @registry.tool(emoji=":paperclip:")
    async def send_file(ctx: ToolContext, path: str, message: str = "") -> str:
        """Send a file from the workspace to the current chat room.

        path: relative path to the file in workspace
        message: optional message to include with the file
        """
        target = _safe_path(ctx.workspace, path)
        if not target.exists():
            return f"File not found: {path}"
        if target.is_dir():
            return f"Cannot send a directory: {path}"

        await client.upload_file(
            ctx.room_id, str(target), message=message, thread_id=ctx.thread_id
        )
        return f"Sent {path} to chat"
