"""Tests for B0.4 + B0.5 — honest parse-mode flags on FileMeta.

Pre-fix (broad-reliability roadmap §B0.4 / §B0.5):

- ``_parse_sync`` called ``extract_pdf(temp_path)`` with the default
  ``ocr="never"`` — scanned exhibits round-tripped as empty bodies.
  The Haiku summarizer then said "the document appears empty" and the
  agent confidently answered from a fabricated summary (issues
  #406 / #407 NDA hallucination).
- ``_parse_sync`` called ``parse_docx(temp_path)`` with the default
  ``track_changes=False`` — M&A redlines lost insertions/deletions,
  the agent saw a phantom "final accepted" version, and couldn't
  identify what changed in the negotiation.

Post-fix, the SPA backend passes ``ocr="auto"`` and ``track_changes=True``
and exposes two honest flags on the FileMeta sidecar so the UI can
render banners:

- ``FileMeta.ocr_applied`` — True when the parsed PDF contains at
  least one block whose provenance.extractor starts with
  ``"kaos-pdf/ocr/"``.
- ``FileMeta.track_changes_detected`` — True when the parsed DOCX
  contains at least one annotation of kind ``TRACKED_CHANGE``.
"""

from __future__ import annotations

import inspect
from typing import Any

from app.services import uploads as uploads_mod

# ── _detect_parse_flags contract tests ──────────────────────────────


class _FakeProv:
    def __init__(self, extractor: str | None) -> None:
        self.extractor = extractor


class _FakeAttr:
    def __init__(self, extractor: str | None) -> None:
        self.provenance = _FakeProv(extractor) if extractor else None


class _FakeBlock:
    def __init__(self, extractor: str | None) -> None:
        self.attr = _FakeAttr(extractor)


class _FakeAnnotation:
    def __init__(self, kind: Any) -> None:
        # Real Annotation discriminator is ``.type``. a5cbda1 fixed the
        # production code to look at ``.type``; tests must mirror.
        self.type = kind


class _FakeDocPDF:
    def __init__(self, extractors: list[str | None]) -> None:
        # ContentDocument stores its block sequence on ``.body`` (tuple).
        # a5cbda1 fixed the production code to walk ``.body``; tests
        # must mirror, or the detection branch reads an empty sequence.
        self.body = tuple(_FakeBlock(e) for e in extractors)


class _FakeDocDOCX:
    def __init__(self, kinds: list[Any]) -> None:
        self.body: tuple[Any, ...] = ()
        self.annotations = [_FakeAnnotation(k) for k in kinds]


class TestDetectParseFlags:
    """``_detect_parse_flags`` reports honest signals or False on failure."""

    def test_pdf_with_ocr_provenance_flags_ocr_applied(self) -> None:
        doc = _FakeDocPDF(
            extractors=[
                "kaos-pdf/pypdfium2",
                "kaos-pdf/ocr/tesseract",  # ← OCR'd block
                "kaos-pdf/pypdfium2",
            ]
        )
        flags = uploads_mod._detect_parse_flags(doc, ".pdf")
        assert flags == {"ocr_applied": True, "track_changes_detected": False}

    def test_pdf_with_only_native_text_flags_no_ocr(self) -> None:
        """Born-digital PDF — even with ocr='auto', no OCR fired."""
        doc = _FakeDocPDF(extractors=["kaos-pdf/pypdfium2"] * 5)
        flags = uploads_mod._detect_parse_flags(doc, ".pdf")
        assert flags == {"ocr_applied": False, "track_changes_detected": False}

    def test_pdf_with_no_provenance_does_not_crash(self) -> None:
        """Edge: a block without provenance — must not raise."""
        doc = _FakeDocPDF(extractors=[None, None])
        flags = uploads_mod._detect_parse_flags(doc, ".pdf")
        assert flags == {"ocr_applied": False, "track_changes_detected": False}

    def test_docx_with_tracked_change_annotation_flags_track_changes(self) -> None:
        from kaos_content.model.annotation import AnnotationType

        doc = _FakeDocDOCX(kinds=[AnnotationType.TRACKED_CHANGE])
        flags = uploads_mod._detect_parse_flags(doc, ".docx")
        assert flags == {"ocr_applied": False, "track_changes_detected": True}

    def test_docx_without_revisions_flags_no_track_changes(self) -> None:
        from kaos_content.model.annotation import AnnotationType

        doc = _FakeDocDOCX(kinds=[AnnotationType.DEFINED_TERM])
        flags = uploads_mod._detect_parse_flags(doc, ".docx")
        assert flags == {"ocr_applied": False, "track_changes_detected": False}

    def test_docx_without_annotations_attr_does_not_crash(self) -> None:
        """Edge: an older AST shape without `annotations` — must not raise."""

        class _Bare:
            pass

        flags = uploads_mod._detect_parse_flags(_Bare(), ".docx")
        assert flags == {"ocr_applied": False, "track_changes_detected": False}

    def test_introspection_failure_falls_back_to_false(self) -> None:
        """A parser that raises on attribute access never propagates —
        the upload still succeeds and the UI just doesn't get a banner."""

        class _Boom:
            @property
            def blocks(self) -> Any:
                raise RuntimeError("provenance walk exploded")

        flags = uploads_mod._detect_parse_flags(_Boom(), ".pdf")
        assert flags == {"ocr_applied": False, "track_changes_detected": False}

    def test_pptx_extension_returns_both_false(self) -> None:
        """PPTX doesn't use OCR or track-changes — fall-through path."""
        doc = _FakeDocPDF(extractors=["kaos-pdf/ocr/tesseract"])
        flags = uploads_mod._detect_parse_flags(doc, ".pptx")
        # ext is not ".pdf" or ".docx" → neither branch runs.
        assert flags == {"ocr_applied": False, "track_changes_detected": False}


# ── _parse_sync wiring tests ────────────────────────────────────────


class TestParseSyncKwargs:
    """``_parse_sync`` must pass the B0.4 / B0.5 kwargs to the underlying
    parsers. We assert via inspecting the source — these tests fail loud
    if a future edit drops the kwargs."""

    def test_parse_sync_passes_ocr_auto_to_extract_pdf(self) -> None:
        source = inspect.getsource(uploads_mod._parse_sync)
        # The exact form in the function body — fail-loud if removed.
        assert 'extract_pdf(temp_path, ocr="auto")' in source, (
            "B0.4 regression: ``_parse_sync`` no longer passes ``ocr='auto'`` "
            "to ``extract_pdf``. Scanned exhibits will silently round-trip "
            "with empty bodies — see roadmap §B0.4."
        )

    def test_parse_sync_passes_track_changes_true_to_parse_docx(self) -> None:
        source = inspect.getsource(uploads_mod._parse_sync)
        assert "parse_docx(temp_path, track_changes=True)" in source, (
            "B0.5 regression: ``_parse_sync`` no longer passes "
            "``track_changes=True`` to ``parse_docx``. M&A redlines will "
            "lose insertions/deletions — see roadmap §B0.5."
        )


class TestFileMetaShape:
    """``FileMeta`` carries the two new boolean flags so they survive the
    sidecar JSON round-trip and the SPA UI can read them."""

    def test_file_meta_defaults_for_legacy_sidecars(self) -> None:
        from datetime import UTC, datetime

        from kaos_ui.uploads import FileMeta, FileParseStatus

        # No ocr_applied / track_changes_detected passed — defaults must
        # be False so previously-uploaded files load without re-parse.
        meta = FileMeta(
            filename="legacy.pdf",
            size_bytes=1,
            uploaded_at=datetime.now(UTC),
            parse=FileParseStatus(status="ready"),
        )
        assert meta.ocr_applied is False
        assert meta.track_changes_detected is False

    def test_file_meta_flags_round_trip_through_json(self) -> None:
        from datetime import UTC, datetime

        from kaos_ui.uploads import FileMeta, FileParseStatus

        original = FileMeta(
            filename="scanned.pdf",
            size_bytes=42_000,
            uploaded_at=datetime.now(UTC),
            parse=FileParseStatus(status="ready"),
            ocr_applied=True,
            track_changes_detected=False,
        )
        wire = original.model_dump_json()
        round_tripped = FileMeta.model_validate_json(wire)
        assert round_tripped.ocr_applied is True
        assert round_tripped.track_changes_detected is False
