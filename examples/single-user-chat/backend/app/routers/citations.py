"""/v1/chat/sessions/{session_id}/citations — typed citation extraction.

P2-1 wire-in. The SPA POSTs the assistant's final response text after
each turn lands; we run `kaos_citations.extract_citations` over it and
return the typed Citation records.

Why post-turn extraction instead of a wire-tap on `tool_call/complete`
events: kaos-agents 0.1.0a1 truncates `attributes.result_summary` to
200 chars on the SSE wire (see `kaos_agents.patterns.chat:295`), so
the structured Citation list never reaches the SPA via the stream.
The agent still uses `kaos-citations-extract` during reasoning — the
backend pass here is purely for SPA-side display, not for grounding.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import require_auth
from app.deps import get_session_store
from app.exceptions import SessionNotFoundError
from app.logging_setup import app_logger
from app.models import ExtractCitationsBody, ExtractCitationsResponse
from app.persistence.sessions import SessionStore

router = APIRouter(tags=["citations"], dependencies=[Depends(require_auth)])
logger = app_logger("citations_router")

StoreDep = Annotated[SessionStore, Depends(get_session_store)]


@router.post(
    "/sessions/{session_id}/citations",
    response_model=ExtractCitationsResponse,
)
async def extract_session_citations(
    session_id: str,
    body: ExtractCitationsBody,
    store: StoreDep,
) -> ExtractCitationsResponse:
    """Extract typed Bluebook / financial / accounting citations from `text`.

    The session must exist (the SPA only calls this from a session
    detail route). We don't persist results — citations live in SPA
    state for the lifetime of the route, refreshed on every turn.
    """
    try:
        await store.get(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # kaos-citations is a declared dep; import at request-time so a
    # missing install surfaces as a clear 503 rather than a 500 at
    # app startup.
    try:
        from kaos_citations import extract_citations
    except ImportError as exc:
        logger.warning("kaos_citations is not installed; citation extraction disabled")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "what": "Citation extraction is not available in this backend.",
                "how_to_fix": "Install `kaos-citations` and restart the server.",
            },
        ) from exc

    citations = extract_citations(body.text)
    return ExtractCitationsResponse(
        session_id=session_id,
        count=len(citations),
        citations=[c.model_dump(mode="json") for c in citations],
    )
