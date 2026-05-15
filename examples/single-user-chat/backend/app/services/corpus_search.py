"""P2-3 — BM25 corpus search over the session's uploaded files.

Walks the per-session ``.kaos.json`` AST sidecars, serializes each
ContentDocument to markdown, indexes the resulting text with
`kaos_nlp_core.search.Searcher` (paragraph-level), and returns the
top-k matches with a per-hit snippet + score.

Out of scope for v1:
  - Cross-session search (different surface — needs an index spanning
    the user's whole sidebar).
  - Re-ranking (BM25 is good enough for the legal-document use case
    we have today; the agent does the post-narrow if needed).
"""

from __future__ import annotations

from dataclasses import dataclass

from kaos_core import KaosRuntime
from kaos_core.logging import get_logger

logger = get_logger("kaos.app.chat.corpus_search")


@dataclass(frozen=True, slots=True)
class CorpusSearchHit:
    """One BM25 hit. Frozen value type — serializable via dataclasses."""

    filename: str
    score: float
    snippet: str
    char_offset: int


async def search_session_corpus(
    *,
    runtime: KaosRuntime,
    session_id: str,
    query: str,
    top_k: int = 10,
) -> list[CorpusSearchHit]:
    """BM25-search the ready-parsed files in ``session_id``.

    Returns at most ``top_k`` hits ordered by descending score. Files
    whose parse failed are skipped silently (no AST to index). Returns
    an empty list when no files are ready OR the query is empty.

    Imports kaos-nlp-core / kaos-content lazily so the route stays
    optional when those extras aren't installed.
    """
    q = query.strip()
    if not q:
        return []

    # Lazy imports — keep the routing layer importable when the NLP
    # extras aren't on the path.
    try:
        from kaos_content import (  # ty: ignore[unresolved-import]
            ContentDocument,
            serialize_markdown,
        )
        from kaos_nlp_core.search import (  # ty: ignore[unresolved-import]
            DocumentCollection,
            Searcher,
        )
    except ImportError as exc:
        logger.warning("kaos_nlp_core / kaos_content not importable: %s", exc)
        return []

    # Build (filename, paragraphs) by walking the AST sidecars. Each
    # paragraph becomes one DocumentCollection record so BM25 can
    # rank per-paragraph rather than per-file — granular hits make
    # the SPA's "jump to passage" UX feasible later.
    prefix = f"sessions/{session_id}/files/"
    paths = await runtime.vfs.list(prefix)
    records: list[dict[str, str | int]] = []
    rec_id = 0
    for path in sorted(paths):
        if not path.endswith(".kaos.json"):
            continue
        filename = path[len(prefix) : -len(".kaos.json")]
        try:
            ast_bytes = await runtime.vfs.read(path)
            doc = ContentDocument.model_validate_json(ast_bytes)
            text = serialize_markdown(doc)
        except Exception as exc:
            logger.warning(
                "skipping unreadable AST for session=%s file=%s: %s",
                session_id,
                filename,
                exc,
                extra={"session_id": session_id, "filename": filename},
            )
            continue

        offset = 0
        for paragraph in text.split("\n\n"):
            chunk = paragraph.strip()
            if not chunk or len(chunk) < 20:
                # Skip tiny paragraphs (figure captions / single
                # words) — they pollute the score distribution.
                offset += len(paragraph) + 2
                continue
            records.append(
                {
                    "id": f"{filename}#{rec_id}",
                    "text": chunk,
                    "filename": filename,
                    "char_offset": offset,
                }
            )
            rec_id += 1
            offset += len(paragraph) + 2

    if not records:
        return []

    collection = DocumentCollection.from_records(
        records,
        id_field="id",
        text_field="text",
        metadata_fields=("filename", "char_offset"),
    )
    searcher = Searcher.from_collection(collection)
    hits = searcher.search(q, top_k=top_k)

    out: list[CorpusSearchHit] = []
    for hit in hits:
        meta = hit.document.metadata if hasattr(hit, "document") else {}
        out.append(
            CorpusSearchHit(
                filename=str(meta.get("filename", "?")),
                score=float(hit.score),
                snippet=hit.document.text[:300] if hasattr(hit, "document") else "",
                char_offset=int(meta.get("char_offset", 0)),
            )
        )
    return out


__all__ = ["CorpusSearchHit", "search_session_corpus"]
