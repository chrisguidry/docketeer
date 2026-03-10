from docketeer.testing import MemoryChat
from docketeer.tools import ToolContext, registry
from docketeer_slack import register_tools


async def test_send_file_passes_thread_id(tool_context: ToolContext):
    chat = MemoryChat()
    (tool_context.workspace / "test.txt").write_text("hello")
    tool_context.thread_id = "1718123456.123456"
    register_tools(chat, tool_context)
    result = await registry.execute("send_file", {"path": "test.txt"}, tool_context)
    assert "Sent" in result
    assert chat.uploaded_files[0].thread_id == "1718123456.123456"
