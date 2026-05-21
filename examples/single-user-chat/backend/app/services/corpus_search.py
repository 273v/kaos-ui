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
    """One BM25 hit. Frozen value type — serializable via dataclasses.

    B0.6 (broad-reliability roadmap): the structural citation fields
    (``block_ref``, ``page``, ``section_title``, ``path``) flow through
    from kaos-content's :class:`SearchResult` so the SPA can render
    grounded citations and the agent cannot fabricate "Section X"
    labels on paragraphs whose AST has none.

    The kaos-content contract is explicit (see ``kaos_content.search``
    docstring): "Agents that need to cite a position in a document
    MUST draw the section identifier from ``path`` — empty ``path``
    is the contract that no structural identifier is available for
    this hit, and any 'Section N' claim about it would be a
    fabrication." Empty ``path`` here means the same.

    All new fields default to safe sentinels so legacy callers /
    older JSON payloads round-trip without crashing.
    """

    filename: str
    score: float
    snippet: str
    char_offset: int
    # B0.6 — structural citation grounding fields. Empty / None means
    # "no structural identifier available"; the agent must not invent
    # one. Empty defaults keep the dataclass shape compatible with any
    # caller that constructs hits without the AST refs.
    block_ref: str | None = None
    page: int | None = None
    section_title: str | None = None
    path: tuple[str, ...] = ()


async def search_session_corpus(
    *,
    runtime: KaosRuntime,
    session_id: str,
    query: str,
    top_k: int = 10,
    tenant_id: str | None = None,
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
    # extras aren't on the path. B0.6: switched from
    # serialize_markdown-then-split (which discarded AST refs) to
    # kaos-content's :class:`SearchableCorpus` so the structural
    # citation fields (block_ref, page, section_title, path) flow
    # through to the SPA.
    try:
        from kaos_content import ContentDocument
        from kaos_content.indexing import SearchableCorpus
    except ImportError as exc:
        logger.warning("kaos_content not importable: %s", exc)
        return []

    from app.services.uploads import _vfs_prefix

    prefix = _vfs_prefix(session_id, tenant_id)
    paths = await runtime.vfs.list(prefix)

    docs: list[ContentDocument] = []
    doc_filenames: list[str] = []
    for path in sorted(paths):
        if not path.endswith(".kaos.json"):
            continue
        filename = path[len(prefix) : -len(".kaos.json")]
        try:
            ast_bytes = await runtime.vfs.read(path)
            doc = ContentDocument.model_validate_json(ast_bytes)
        except Exception as exc:
            logger.warning(
                "skipping unreadable AST for session=%s file=%s: %s",
                session_id,
                filename,
                exc,
                extra={"session_id": session_id, "filename": filename},
            )
            continue
        docs.append(doc)
        doc_filenames.append(filename)

    if not docs:
        return []

    # Build a single corpus-wide BM25 index — IDF spans the full
    # session corpus, the same way the agent's downstream retrieval
    # would see it. ``doc_uris=doc_filenames`` lets ``SearchResult.doc_uri``
    # carry the filename so we don't have to keep a parallel mapping.
    corpus = SearchableCorpus(docs, doc_uris=doc_filenames)
    results = corpus.search(q, top_k=top_k, preview_length=300)

    out: list[CorpusSearchHit] = []
    for hit in results.results:
        # ``hit.doc_uri`` was set from ``doc_filenames`` so it IS the
        # filename. Fall back to ``doc_index`` only when ``doc_uri`` is
        # somehow None.
        filename = hit.doc_uri or (
            doc_filenames[hit.doc_index] if hit.doc_index is not None else "?"
        )
        out.append(
            CorpusSearchHit(
                filename=filename,
                score=float(hit.score),
                snippet=hit.text[:300],
                # ``char_offset`` is no longer meaningful at the
                # corpus-search layer (the inner segmentation is
                # AST-rooted, not text-offset-rooted). Surface
                # block_ref / path instead as the citation handles.
                char_offset=hit.char_start or 0,
                block_ref=hit.block_ref or None,
                page=hit.page,
                section_title=hit.section_title,
                path=tuple(hit.path or ()),
            )
        )
    return out


__all__ = ["CorpusSearchHit", "search_session_corpus"]
