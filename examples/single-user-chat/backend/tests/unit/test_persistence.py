"""SessionStore CRUD round-trip + pagination + archive."""

from __future__ import annotations

import pytest

from app.exceptions import SessionNotFoundError

pytestmark = pytest.mark.unit


async def test_create_get_round_trip(session_store):
    meta = await session_store.create(
        title="Hello",
        model="anthropic:claude-haiku-4-5",
        system_prompt="Be helpful.",
    )
    assert meta.title == "Hello"
    assert meta.model == "anthropic:claude-haiku-4-5"
    assert meta.tools_enabled is False
    assert meta.message_count == 0
    assert meta.last_message_at is None
    assert meta.archived is False

    fetched = await session_store.get(meta.id)
    assert fetched == meta


async def test_get_missing_raises(session_store):
    with pytest.raises(SessionNotFoundError) as exc:
        await session_store.get("nonexistent-id")
    msg = str(exc.value)
    # Agent-friendly error: must include what + how + alternative
    assert "How to fix" in msg
    assert "Alternative" in msg


async def test_patch_partial_update(session_store):
    meta = await session_store.create(
        title="Original",
        model="anthropic:claude-haiku-4-5",
        system_prompt="A",
    )
    patched = await session_store.patch(meta.id, title="Renamed", model="openai:gpt-5")
    assert patched.title == "Renamed"
    assert patched.model == "openai:gpt-5"
    # Unchanged fields stay.
    assert patched.system_prompt == "A"
    assert patched.tools_enabled is False
    assert patched.id == meta.id


async def test_touch_bumps_counter_and_timestamp(session_store):
    meta = await session_store.create(
        title="x", model="anthropic:claude-haiku-4-5", system_prompt=""
    )
    assert meta.message_count == 0
    assert meta.last_message_at is None

    bumped = await session_store.touch(meta.id, increment_messages=1)
    assert bumped.message_count == 1
    assert bumped.last_message_at is not None

    bumped2 = await session_store.touch(meta.id, increment_messages=2)
    assert bumped2.message_count == 3


async def test_list_newest_first(session_store):
    a = await session_store.create(title="A", model="anthropic:claude-haiku-4-5", system_prompt="")
    b = await session_store.create(title="B", model="anthropic:claude-haiku-4-5", system_prompt="")
    c = await session_store.create(title="C", model="anthropic:claude-haiku-4-5", system_prompt="")
    # Touch b last so it's most recent.
    await session_store.touch(b.id, increment_messages=1)

    sums, _cursor = await session_store.list(limit=10)
    ids = [s.id for s in sums]
    # b touched last, so first. a + c sort by created_at.
    assert ids[0] == b.id
    assert set(ids) == {a.id, b.id, c.id}


async def test_archive_moves_and_404s(session_store):
    meta = await session_store.create(
        title="x", model="anthropic:claude-haiku-4-5", system_prompt=""
    )
    archived_at = await session_store.archive(meta.id)
    assert archived_at is not None

    # The active path is gone.
    with pytest.raises(SessionNotFoundError):
        await session_store.get(meta.id)

    # The archived-namespace list contains it.
    archived, _ = await session_store.list(archived=True)
    assert len(archived) == 1
    assert archived[0].id == meta.id
    assert archived[0].archived is True


async def test_default_tools_enabled_false(session_store):
    meta = await session_store.create(
        title="x", model="anthropic:claude-haiku-4-5", system_prompt=""
    )
    assert meta.tools_enabled is False


async def test_explicit_session_id(session_store):
    meta = await session_store.create(
        title="x",
        model="anthropic:claude-haiku-4-5",
        system_prompt="",
        session_id="my-fixed-id",
    )
    assert meta.id == "my-fixed-id"
    fetched = await session_store.get("my-fixed-id")
    assert fetched.id == "my-fixed-id"
