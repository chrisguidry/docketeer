"""Tests for message and tool serialization in the agentic loop."""

from docketeer.prompt import (
    Base64ImageSourceParam,
    ImageBlockParam,
    MessageParam,
    SystemBlock,
    TextBlockParam,
)


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

    def test_serialize_image_block_to_openai_format(self) -> None:
        from docketeer_deepinfra.loop import _serialize_messages

        img = ImageBlockParam(
            source=Base64ImageSourceParam(media_type="image/png", data="aWZha2U=")
        )
        result = _serialize_messages([], [MessageParam(role="user", content=[img])])
        block = result[0]["content"][0]
        assert block["type"] == "image_url"
        assert block["image_url"]["url"] == "data:image/png;base64,aWZha2U="

    def test_serialize_mixed_text_and_image(self) -> None:
        from docketeer_deepinfra.loop import _serialize_messages

        img = ImageBlockParam(
            source=Base64ImageSourceParam(media_type="image/jpeg", data="abc123")
        )
        result = _serialize_messages(
            [],
            [
                MessageParam(
                    role="user",
                    content=[TextBlockParam(text="look at this"), img],
                )
            ],
        )
        content = result[0]["content"]
        assert content[0] == {"type": "text", "text": "look at this"}
        assert content[1]["type"] == "image_url"
        assert "data:image/jpeg;base64,abc123" in content[1]["image_url"]["url"]

    def test_serialize_content_as_list_with_to_dict(self) -> None:
        from docketeer_deepinfra.loop import _serialize_messages

        result = _serialize_messages(
            [], [MessageParam(role="user", content=[TextBlockParam(text="hello")])]
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
    def test_converts_tool_definition(self) -> None:
        from docketeer.tools import ToolDefinition
        from docketeer_deepinfra.loop import _tool_to_dict

        tool = ToolDefinition(
            name="my_tool",
            description="Does something useful",
            input_schema={"type": "object", "properties": {}},
        )
        result = _tool_to_dict(tool)
        assert result == {
            "type": "function",
            "function": {
                "name": "my_tool",
                "description": "Does something useful",
                "parameters": {"type": "object", "properties": {}},
            },
        }
