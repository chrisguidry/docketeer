"""Tests for the workspace hooks module."""

from pathlib import Path, PurePosixPath

from docketeer.hooks import (
    HookRegistry,
    HookResult,
    WorkspaceHook,
    parse_frontmatter,
    render_frontmatter,
    strip_frontmatter,
)


class TestParseFrontmatter:
    def test_valid_frontmatter(self):
        content = "---\nband: wicket\ntopic: events\n---\nBody text here."
        meta, body = parse_frontmatter(content)
        assert meta == {"band": "wicket", "topic": "events"}
        assert body == "Body text here."

    def test_no_frontmatter(self):
        content = "Just a plain file with no frontmatter."
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert body == content

    def test_empty_frontmatter(self):
        content = "---\n\n---\nBody."
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert body == "---\n\n---\nBody."

    def test_frontmatter_with_list(self):
        content = "---\nfilters:\n  - field: payload.action\n    op: eq\n    value: push\n---\nBody."
        meta, body = parse_frontmatter(content)
        assert meta["filters"] == [
            {"field": "payload.action", "op": "eq", "value": "push"}
        ]
        assert body == "Body."

    def test_frontmatter_non_dict_returns_empty(self):
        content = "---\n- item1\n- item2\n---\nBody."
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert body == content

    def test_frontmatter_with_no_body(self):
        content = "---\nkey: value\n---\n"
        meta, body = parse_frontmatter(content)
        assert meta == {"key": "value"}
        assert body == ""

    def test_frontmatter_with_nested_dict(self):
        content = "---\nsecrets:\n  token: github/webhook-secret\n---\nNotes."
        meta, body = parse_frontmatter(content)
        assert meta == {"secrets": {"token": "github/webhook-secret"}}
        assert body == "Notes."


class TestRenderFrontmatter:
    def test_render_with_body(self):
        meta = {"band": "wicket", "topic": "events"}
        result = render_frontmatter(meta, "Body text.")
        assert result.startswith("---\n")
        assert "band: wicket" in result
        assert result.endswith("---\nBody text.")

    def test_render_empty_body(self):
        meta = {"key": "standup"}
        result = render_frontmatter(meta, "")
        assert result == "---\nkey: standup\n---\n"

    def test_render_roundtrip(self):
        original = "---\nband: wicket\ntopic: events\n---\nMonitor events."
        meta, body = parse_frontmatter(original)
        rendered = render_frontmatter(meta, body)
        meta2, body2 = parse_frontmatter(rendered)
        assert meta2 == meta
        assert body2 == body


class TestStripFrontmatter:
    def test_strips_frontmatter(self):
        content = "---\nkey: value\n---\nBody text."
        assert strip_frontmatter(content) == "Body text."

    def test_no_frontmatter_returns_all(self):
        content = "Just text."
        assert strip_frontmatter(content) == "Just text."


class FakeHook:
    def __init__(self, prefix: str) -> None:
        self.prefix = PurePosixPath(prefix)
        self._scan_error: Exception | None = None
        self._scan_calls: list[Path] = []
        self._validate_calls: list[tuple[PurePosixPath, str]] = []
        self._commit_calls: list[tuple[PurePosixPath, str]] = []
        self._delete_calls: list[PurePosixPath] = []

    async def validate(self, path: PurePosixPath, content: str) -> HookResult | None:
        self._validate_calls.append((path, content))
        return HookResult("validated")

    async def commit(self, path: PurePosixPath, content: str) -> None:
        self._commit_calls.append((path, content))

    async def on_delete(self, path: PurePosixPath) -> str | None:
        self._delete_calls.append(path)
        return "deleted"

    async def scan(self, workspace: Path) -> None:
        self._scan_calls.append(workspace)
        if self._scan_error:
            raise self._scan_error


def test_fake_hook_is_workspace_hook():
    hook = FakeHook("tunings")
    assert isinstance(hook, WorkspaceHook)


async def test_fake_hook_validate():
    hook = FakeHook("tunings")
    result = await hook.validate(PurePosixPath("tunings/test.md"), "content")
    assert result is not None
    assert result.message == "validated"
    assert hook._validate_calls == [(PurePosixPath("tunings/test.md"), "content")]


async def test_fake_hook_commit():
    hook = FakeHook("tunings")
    await hook.commit(PurePosixPath("tunings/test.md"), "content")
    assert hook._commit_calls == [(PurePosixPath("tunings/test.md"), "content")]


async def test_fake_hook_on_delete():
    hook = FakeHook("tunings")
    result = await hook.on_delete(PurePosixPath("tunings/test.md"))
    assert result == "deleted"
    assert hook._delete_calls == [PurePosixPath("tunings/test.md")]


class TestHookRegistry:
    def test_find_hook_matching_prefix(self):
        reg = HookRegistry()
        hook = FakeHook("tunings")
        reg.register(hook)

        found = reg.find_hook(PurePosixPath("tunings/github.md"))
        assert found is hook

    def test_find_hook_no_match(self):
        reg = HookRegistry()
        hook = FakeHook("tunings")
        reg.register(hook)

        found = reg.find_hook(PurePosixPath("other/file.md"))
        assert found is None

    def test_find_hook_nested_path(self):
        reg = HookRegistry()
        hook = FakeHook("tunings")
        reg.register(hook)

        found = reg.find_hook(PurePosixPath("tunings/sub/deep/file.md"))
        assert found is hook

    def test_find_hook_first_match_wins(self):
        reg = HookRegistry()
        hook1 = FakeHook("tunings")
        hook2 = FakeHook("tunings")
        reg.register(hook1)
        reg.register(hook2)

        found = reg.find_hook(PurePosixPath("tunings/test.md"))
        assert found is hook1

    def test_find_hook_exact_prefix_partial_no_match(self):
        reg = HookRegistry()
        hook = FakeHook("tasks")
        reg.register(hook)

        found = reg.find_hook(PurePosixPath("tasks-extra/file.md"))
        assert found is None

    async def test_scan_all_calls_every_hook(self, tmp_path: Path):
        reg = HookRegistry()
        hook1 = FakeHook("tunings")
        hook2 = FakeHook("tasks")
        reg.register(hook1)
        reg.register(hook2)

        await reg.scan_all(tmp_path)

        assert hook1._scan_calls == [tmp_path]
        assert hook2._scan_calls == [tmp_path]

    async def test_scan_all_continues_on_error(self, tmp_path: Path):
        reg = HookRegistry()
        hook1 = FakeHook("tunings")
        hook1._scan_error = RuntimeError("boom")
        hook2 = FakeHook("tasks")
        reg.register(hook1)
        reg.register(hook2)

        await reg.scan_all(tmp_path)

        assert hook2._scan_calls == [tmp_path]

    def test_empty_registry_find_returns_none(self):
        reg = HookRegistry()
        assert reg.find_hook(PurePosixPath("anything")) is None

    async def test_empty_registry_scan_is_noop(self, tmp_path: Path):
        reg = HookRegistry()
        await reg.scan_all(tmp_path)
