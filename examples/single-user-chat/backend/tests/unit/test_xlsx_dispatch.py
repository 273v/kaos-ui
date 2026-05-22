"""Unit test for #589/Issue-5 — ``.xlsx`` upload dispatch.

Pre-fix: ``app/services/uploads.py`` only handled .pdf/.docx/.pptx;
uploading .xlsx raised ``UploadValidationError`` despite kaos-office
shipping ``parse_xlsx`` (with formula preservation). The legal-AI
audit's M2.1 finding (implemented-but-never-invoked).

Post-fix: .xlsx routes to ``parse_xlsx`` and produces a
``TabularDocument`` that ``_serialize_doc`` can round-trip.
"""

from __future__ import annotations

from pathlib import Path

import pytest


_FIXTURE = Path(
    "/home/mjbommar/projects/273v/kaos-office/tests/fixtures/xlsx/states.xlsx"
)


@pytest.mark.unit
@pytest.mark.skipif(not _FIXTURE.exists(), reason="kaos-office xlsx fixture missing")
def test_xlsx_dispatch_returns_tabular_document() -> None:
    """`.xlsx` extension routes to ``parse_xlsx`` and returns a
    TabularDocument that supports the downstream ``model_dump_json``
    contract used by ``_serialize_doc``.
    """
    from app.services.uploads import _parse_sync

    doc = _parse_sync(_FIXTURE, ".xlsx")
    # parse_xlsx returns TabularDocument (kaos-content). Both
    # TabularDocument and ContentDocument are Pydantic v2 models, so
    # ``model_dump_json`` is the round-trip contract _serialize_doc
    # expects.
    assert hasattr(doc, "model_dump_json"), (
        "parse_xlsx return value must expose Pydantic ``model_dump_json``"
    )
    payload = doc.model_dump_json()
    assert isinstance(payload, str)
    assert len(payload) > 100  # tabular doc should not be empty


@pytest.mark.unit
@pytest.mark.skipif(not _FIXTURE.exists(), reason="kaos-office xlsx fixture missing")
def test_xlsx_serialize_doc_round_trip() -> None:
    """``_serialize_doc`` must produce non-empty bytes for an xlsx-
    parsed TabularDocument — the contract the upload pipeline depends
    on for writing the AST sidecar.
    """
    from app.services.uploads import _parse_sync, _serialize_doc

    doc = _parse_sync(_FIXTURE, ".xlsx")
    payload = _serialize_doc(doc)
    assert isinstance(payload, bytes)
    assert len(payload) > 100


@pytest.mark.unit
def test_xlsx_in_supported_extensions() -> None:
    """The default supported_extensions tuple now includes ``.xlsx``."""
    from app.settings import AppSettings

    settings = AppSettings()
    assert ".xlsx" in settings.supported_upload_extensions


@pytest.mark.unit
def test_parse_flags_safe_for_xlsx() -> None:
    """``_detect_parse_flags`` on a TabularDocument must not raise and
    must return both-False (xlsx has no OCR + no track-changes notion).
    """
    from app.services.uploads import _detect_parse_flags

    # Pass a minimal stub — _detect_parse_flags is the safety net
    # for arbitrary parsed_doc shapes. The .xlsx branch is not in the
    # ext-dispatch so this just exercises the default-fall-through.
    class _StubDoc:
        body = ()

    flags = _detect_parse_flags(_StubDoc(), ".xlsx")
    assert flags == {"ocr_applied": False, "track_changes_detected": False}
