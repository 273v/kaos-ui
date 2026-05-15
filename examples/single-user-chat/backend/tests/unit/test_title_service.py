"""Unit tests for app.services.title._should_retitle.

Regression net for the auto-titler cadence — particularly the
pre-existing-session footgun where `title_source` defaults to
``"auto"`` and `title_updated_at` defaults to ``None`` on old
meta.json files. Without the guard those sessions would get re-titled
on every turn and overwrite the user's heuristic titles.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import SessionMeta
from app.services.title import _should_retitle


def _meta(
    *,
    title_source: str = "auto",
    message_count: int = 4,
    title_updated_at: datetime | None = None,
) -> SessionMeta:
    """Build a SessionMeta with sane defaults for the title-cadence tests."""
    return SessionMeta(
        id="01HX0000000000000000000000",
        title="something",
        model="anthropic:claude-haiku-4-5",
        system_prompt="",
        tools_enabled=True,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        last_message_at=datetime(2026, 5, 14, tzinfo=UTC),
        message_count=message_count,
        title_source=title_source,  # type: ignore[arg-type]
        title_updated_at=title_updated_at,
    )


def test_manual_title_is_never_overwritten() -> None:
    """User-renamed sessions stay put forever."""
    assert (
        _should_retitle(
            _meta(
                title_source="manual",
                message_count=2,
                title_updated_at=None,
            )
        )
        is False
    )
    assert (
        _should_retitle(
            _meta(
                title_source="manual",
                message_count=10,
                title_updated_at=datetime.now(UTC) - timedelta(days=30),
            )
        )
        is False
    )


def test_first_turn_always_retitles() -> None:
    """A brand-new session with one user→assistant turn lands at count=2."""
    assert _should_retitle(_meta(message_count=2, title_updated_at=None)) is True
    # Edge: count=1 (mid-stream, somehow) also retitles.
    assert _should_retitle(_meta(message_count=1)) is True


def test_every_tenth_turn_retitles() -> None:
    """The natural refresh cadence."""
    for count in (10, 20, 30, 100):
        assert _should_retitle(_meta(message_count=count)) is True, count


def test_pre_existing_session_left_alone_off_cadence() -> None:
    """Regression: title_source='auto' + title_updated_at=None should NOT
    retitle on every turn just because we've never auto-titled the session.

    This is the bug the fix-up commit closed. The auto-titler used to
    treat `title_updated_at is None` as "first run, please retitle";
    that meant every turn against an older chat would clobber its
    heuristic title.
    """
    for count in (3, 4, 5, 6, 7, 8, 9, 11, 13, 99):
        assert _should_retitle(_meta(message_count=count, title_updated_at=None)) is False, count


def test_stale_auto_title_refreshes_after_24h() -> None:
    """Once we've auto-titled, the 24h fallback can kick in."""
    stale = datetime.now(UTC) - timedelta(hours=25)
    assert _should_retitle(_meta(message_count=5, title_updated_at=stale)) is True


def test_fresh_auto_title_off_cadence_does_not_refresh() -> None:
    """If we titled recently and we're not on a boundary, leave it."""
    fresh = datetime.now(UTC) - timedelta(hours=1)
    assert _should_retitle(_meta(message_count=5, title_updated_at=fresh)) is False
    # But a boundary still fires regardless of freshness.
    assert _should_retitle(_meta(message_count=10, title_updated_at=fresh)) is True
