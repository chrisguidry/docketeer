"""Tests for message and tool serialization in the agentic loop."""

from unittest.mock import MagicMock

from docketeer.prompt import MessageParam, SystemBlock


class TestSerializeMessages:
    def test_serialize_empty(self) -> None:
        from docketeer_deepinfra.loop import _serialize_messages

        assert _serialize_messages([], []) == []

    def test_serialize_system_message(self) -> None:
        from docketeer_deepinfra.loop import _serialize_messages

        result = _serialize_messages(
            [SystemBlock(text="You are helpful.")],
            [MessageParam(role="user", content="hello")],
        )
        assert result[0] == {"role": "system", "content": "You are helpful."}
        assert result[1]["role"] == "user"

    def test_serialize_tool_result_message(self) -> None:
        from docketeer_deepinfra.loop import _serialize_messages

        result = _serialize_messages(
            [],
            [MessageParam(role="tool", content="file list", tool_call_id="call_abc")],
        )
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "call_abc"
        assert result[0]["content"] == "file list"

    def test_serialize_content_as_list_with_to_dict(self) -> None:
        from docketeer_deepinfra.loop import _serialize_messages

        class FakeTextPart:
            def to_dict(self) -> dict[str, str]:
                return {"type": "text", "text": "hello"}

        result = _serialize_messages(
            [], [MessageParam(role="user", content=[FakeTextPart()])]
        )
        assert result[0]["content"] == [{"type": "text", "text": "hello"}]

    def test_serialize_content_as_list_with_dict(self) -> None:
        from docketeer_deepinfra.loop import _serialize_messages

        result = _serialize_messages(
            [],
            [MessageParam(role="user", content=[{"type": "text", "text": "hello"}])],
        )
        assert result[0]["content"] == [{"type": "text", "text": "hello"}]

    def test_serialize_empty_string_content(self) -> None:
        from docketeer_deepinfra.loop import _serialize_messages

        result = _serialize_messages([], [MessageParam(role="user", content="")])
        assert result[0]["content"] == ""

    def test_serialize_tool_calls_attribute(self) -> None:
        from docketeer_deepinfra.loop import _serialize_messages

        tool_calls = [{"id": "call_1", "function": {"name": "foo", "arguments": "{}"}}]
        result = _serialize_messages(
            [],
            [MessageParam(role="assistant", content="", tool_calls=tool_calls)],
        )
        assert result[0]["tool_calls"] == tool_calls

    def test_falsy_tool_call_id_omitted(self) -> None:
        from docketeer_deepinfra.loop import _serialize_messages

        msg = MessageParam(role="tool", content="result")
        msg.tool_call_id = ""
        result = _serialize_messages([], [msg])
        assert "tool_call_id" not in result[0]


class TestToolToDict:
    def test_tool_with_to_api_dict(self) -> None:
        from docketeer_deepinfra.loop import _tool_to_dict

        tool = MagicMock()
        tool.to_api_dict.return_value = {
            "type": "function",
            "function": {"name": "list_files", "parameters": {}},
        }
        result = _tool_to_dict(tool)
        assert result == {
            "type": "function",
            "function": {"name": "list_files", "parameters": {}},
        }

    def test_tool_fallback_without_to_api_dict(self) -> None:
        from docketeer_deepinfra.loop import _tool_to_dict

        tool = MagicMock(spec=["name", "input_schema"])
        tool.name = "my_tool"
        tool.input_schema = {"type": "object", "properties": {}}

        result = _tool_to_dict(tool)
        assert result == {
            "type": "function",
            "function": {
                "name": "my_tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }
