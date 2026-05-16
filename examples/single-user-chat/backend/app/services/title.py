"""Background session-title auto-summarizer.

After every chat turn, we evaluate whether the session's title should
be refreshed by an LLM Program. Only "auto"-sourced titles are
refreshed — once the user renames a session manually, we leave it
alone forever.

Refresh cadence:
- First turn (`message_count` flips from 0 → 2 after the post-stream
  bump) → always re-title from the conversation
- Every 10 turns after that
- Or whenever 24h have passed since the last auto-title

Failures are swallowed; the existing title (heuristic or prior auto)
sticks. Title regeneration is best-effort polish, never a hard error.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kaos_llm_core.programs import llm_call

from app.exceptions import SessionNotFoundError
from app.logging_setup import app_logger
from app.models import HistoryMessage, SessionMeta
from app.persistence.sessions import SessionStore

logger = app_logger("title_service")

# Re-title every N messages or after this much wall-clock time, whichever
# fires first. Default model lives in AppSettings.auto_title_model
# (env var APP_AUTO_TITLE_MODEL). We baseline on Haiku at decoration
# time, then pass the configured value at call time so env overrides
# land without re-importing this module.
_REFRESH_EVERY_MESSAGES = 10
_REFRESH_MAX_AGE = timedelta(hours=24)
_TITLE_MAX_INPUT_CHARS = 8_000
_BASELINE_TITLE_MODEL = "anthropic:claude-haiku-4-5"


def _resolve_title_model() -> str:
    """Read the auto-title model from AppSettings at call time so the
    `APP_AUTO_TITLE_MODEL` env var takes effect on every refresh.
    """
    from app.settings import AppSettings

    return AppSettings().auto_title_model


@llm_call(model=_BASELINE_TITLE_MODEL, max_retries=1)
async def summarize_session_title(conversation: str) -> str:  # ty: ignore[empty-body]
    """Read the chat conversation below and produce a short, specific
    title for the session.

    Rules:
    - 3 to 6 words.
    - Title case.
    - No leading "Chat:" / "Discussion of" / "Help with" / "Question about".
    - No trailing punctuation.
    - Be specific about the SUBJECT (e.g. "Rule 10b-5 Scienter Survey"),
      not the SHAPE of the conversation ("Securities Law Question").
    - If the conversation is too short or generic to title meaningfully,
      return exactly: Untitled
    """


def _format_history(messages: list[HistoryMessage]) -> str:
    out: list[str] = []
    used = 0
    for m in messages:
        if m.role not in ("user", "assistant"):
            continue
        role = "User" if m.role == "user" else "Assistant"
        line = f"{role}: {m.content.strip()}"
        if used + len(line) > _TITLE_MAX_INPUT_CHARS:
            line = line[: _TITLE_MAX_INPUT_CHARS - used]
            out.append(line)
            break
        out.append(line)
        used += len(line) + 1
    return "\n\n".join(out)


def _should_retitle(meta: SessionMeta) -> bool:
    """Decide whether the post-turn hook should re-summarize.

    Pre-existing sessions (created before this feature shipped) load
    with `title_source="auto"` and `title_updated_at=None` because
    Pydantic backfills the new fields with defaults. We do NOT want
    to overwrite their heuristic titles on every turn — only on the
    natural cadence (first turn, every 10 messages). The 24h stale
    refresh only fires once we've previously auto-titled the session,
    so it can't surprise older chats.
    """
    if meta.title_source == "manual":
        return False
    if meta.message_count <= 2:
        # First user→assistant turn just landed (count is 2 after the
        # post-stream bump). Always re-title.
        return True
    if meta.message_count % _REFRESH_EVERY_MESSAGES == 0:
        return True
    if meta.title_updated_at is None:
        # Pre-existing session: leave its title alone until the next
        # natural retitle boundary above.
        return False
    age = datetime.now(UTC) - meta.title_updated_at
    return age >= _REFRESH_MAX_AGE


async def maybe_retitle_session(
    *,
    store: SessionStore,
    session_id: str,
    fetch_history,
) -> None:
    """Inspect session state and run the title Program when appropriate.

    `fetch_history` is an injected callable that returns a
    `list[HistoryMessage]` — the chat router has the kaos-agents
    upstream client wired up already, so we pass it in rather than
    re-creating it here.
    """
    try:
        meta = await store.get(session_id)
    except SessionNotFoundError:
        return
    if not _should_retitle(meta):
        return

    try:
        messages = await fetch_history(session_id)
    except Exception as exc:
        logger.warning("title fetch_history failed for %s: %s", session_id, exc)
        return
    if not messages:
        return

    conversation = _format_history(messages)
    if not conversation.strip():
        return

    # kaos-llm-core 0.1.0a7's wrapper rejects unknown kwargs — including
    # the per-call `model=` override that earlier versions accepted. To
    # honor `APP_AUTO_TITLE_MODEL`, build a fresh `Call` at runtime
    # against the same Signature class the decorator generated. When the
    # configured model matches the baseline pinned on the decorator, we
    # skip the rebuild and use the cached call.
    try:
        from kaos_llm_core import Call

        model = _resolve_title_model()
        if model == _BASELINE_TITLE_MODEL:
            title = (await summarize_session_title(conversation=conversation)).strip()
        else:
            sig_cls = summarize_session_title._signature_class  # type: ignore[attr-defined]
            call = Call(sig_cls, model=model, max_retries=1)
            title = (await call(conversation=conversation)).strip()
    except Exception as exc:
        logger.warning("title summarize failed for %s: %s", session_id, exc)
        return

    if not title or title.lower() == "untitled":
        return

    # Trim any stray quotes / trailing punctuation the model adds despite
    # the instruction.
    title = title.strip().strip('"“”').rstrip(".!?,;:")
    if len(title) > 120:
        title = title[:117].rstrip() + "…"

    try:
        await store.patch(
            session_id,
            title=title,
            title_source="auto",
            title_updated_at=datetime.now(UTC),
        )
        logger.info("auto-titled session=%s -> %r", session_id, title)
    except SessionNotFoundError:
        # Race with archive — drop quietly.
        return
