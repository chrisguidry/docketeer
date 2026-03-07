"""Tests for the autonomy context provider."""

from pathlib import Path

from docketeer_autonomy.context import AutonomyContextProvider, create_context_provider


def test_create_context_provider_returns_instance():
    provider = create_context_provider()
    assert isinstance(provider, AutonomyContextProvider)


def test_for_user_with_profile(tmp_path: Path):
    provider = AutonomyContextProvider()
    profile_dir = tmp_path / "people" / "chris"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.md").write_text("# Chris\nLikes coffee")

    msgs = provider.for_user(tmp_path, "chris")
    assert len(msgs) == 1
    assert msgs[0].role == "system"
    assert "What I know about @chris" in msgs[0].content
    assert "Likes coffee" in msgs[0].content


def test_for_user_without_profile(tmp_path: Path):
    provider = AutonomyContextProvider()
    msgs = provider.for_user(tmp_path, "unknown")
    assert len(msgs) == 1
    assert "don't have a profile" in msgs[0].content
    assert "people/unknown/profile.md" in msgs[0].content


def test_for_room_with_notes(tmp_path: Path):
    provider = AutonomyContextProvider()
    rooms = tmp_path / "rooms"
    rooms.mkdir()
    (rooms / "general.md").write_text("Weekly sync every Monday")

    msgs = provider.for_room(tmp_path, "general")
    assert len(msgs) == 1
    assert msgs[0].role == "system"
    assert "Room notes: general" in msgs[0].content
    assert "Weekly sync" in msgs[0].content


def test_for_room_without_notes(tmp_path: Path):
    provider = AutonomyContextProvider()
    msgs = provider.for_room(tmp_path, "general")
    assert len(msgs) == 0
