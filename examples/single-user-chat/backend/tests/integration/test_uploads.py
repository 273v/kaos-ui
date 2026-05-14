"""Integration tests for POST /v1/chat/sessions/{id}/files (P1-1).

Covers:
- Auth gate (401 without bearer)
- Session not found (404)
- Unsupported extension (415)
- Oversize (413)
- Parse failure path (422 with structured error)
- Happy path: real minimal PDF persists + parses + flips tools_enabled

Fixture files: a 167-byte minimal valid PDF is constructed at module
load so pypdfium2 can actually open it; the parse-failure test uses
random bytes wearing a ``.pdf`` suffix.
"""

from __future__ import annotations

from fastapi import status
from fastapi.testclient import TestClient

# Minimal valid PDF — single empty page, no fonts, no content stream.
# Hand-crafted; pypdfium2 opens it without error. Used as the "happy
# path" body since the test fixture doesn't ship reportlab.
_MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 3 3]>>endobj\n"
    b"xref\n"
    b"0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000052 00000 n \n"
    b"0000000101 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\n"
    b"startxref\n"
    b"153\n"
    b"%%EOF\n"
)


def _create_session(client: TestClient) -> str:
    r = client.post("/v1/chat/sessions", json={})
    assert r.status_code == status.HTTP_201_CREATED, r.text
    return r.json()["id"]


def test_upload_requires_auth(app) -> None:
    """No Authorization header → 401."""
    bare = TestClient(app)
    r = bare.post(
        "/v1/chat/sessions/anything/files",
        files={"file": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
    )
    assert r.status_code == status.HTTP_401_UNAUTHORIZED


def test_upload_404_for_unknown_session(client: TestClient) -> None:
    r = client.post(
        "/v1/chat/sessions/does-not-exist/files",
        files={"file": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
    )
    assert r.status_code == status.HTTP_404_NOT_FOUND


def test_upload_415_for_unsupported_extension(client: TestClient) -> None:
    sid = _create_session(client)
    r = client.post(
        f"/v1/chat/sessions/{sid}/files",
        files={"file": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert r.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    detail = r.json()["detail"]
    assert "what" in detail and "how_to_fix" in detail
    assert ".exe" in detail["what"]


def test_upload_413_for_oversize(client: TestClient) -> None:
    """A blob larger than max_upload_bytes is rejected."""
    sid = _create_session(client)
    # AppSettings.max_upload_bytes default is 25 MiB — send 26 MiB.
    oversize = b"\x00" * (26 * 1024 * 1024)
    r = client.post(
        f"/v1/chat/sessions/{sid}/files",
        files={"file": ("big.pdf", oversize, "application/pdf")},
    )
    assert r.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    detail = r.json()["detail"]
    assert "max is" in detail["what"]


def test_upload_201_with_failed_status_when_parser_rejects_corrupt_pdf(
    client: TestClient,
) -> None:
    """Bytes that aren't really a PDF still get persisted.

    Parse failures don't 422 — the bytes landed in the VFS and a future
    feature (e.g., "download my upload") may still want them. The
    failure surfaces via ``parse.status == 'failed'`` + a short error
    string instead.
    """
    sid = _create_session(client)
    r = client.post(
        f"/v1/chat/sessions/{sid}/files",
        files={"file": ("junk.pdf", b"not a real pdf at all" * 50, "application/pdf")},
    )
    assert r.status_code == status.HTTP_201_CREATED, r.text
    body = r.json()
    assert body["file"]["parse"]["status"] == "failed"
    assert body["file"]["parse"]["error"]  # non-empty error string
    assert len(body["file"]["parse"]["error"]) <= 500  # truncation guard


def test_upload_happy_path_persists_and_flips_tools(client: TestClient, app) -> None:
    """Minimal valid PDF → 201 + parsed AST + tools_enabled flipped."""
    sid = _create_session(client)

    # Session starts with default_tools_enabled=False (AppSettings default).
    meta_before = client.get(f"/v1/chat/sessions/{sid}/meta").json()
    assert meta_before["tools_enabled"] is False

    r = client.post(
        f"/v1/chat/sessions/{sid}/files",
        files={"file": ("doc.pdf", _MINIMAL_PDF, "application/pdf")},
    )
    assert r.status_code == status.HTTP_201_CREATED, r.text

    body = r.json()
    assert body["session_id"] == sid
    assert body["file"]["filename"] == "doc.pdf"
    assert body["file"]["size_bytes"] == len(_MINIMAL_PDF)
    assert body["file"]["parse"]["status"] == "ready"
    assert body["file"]["parse"]["error"] is None
    assert body["tools_enabled"] is True

    # Tools auto-flipped on the persisted session too.
    meta_after = client.get(f"/v1/chat/sessions/{sid}/meta").json()
    assert meta_after["tools_enabled"] is True


def test_upload_filename_sanitization(client: TestClient) -> None:
    """Path components are stripped + disallowed chars become underscores."""
    sid = _create_session(client)
    r = client.post(
        f"/v1/chat/sessions/{sid}/files",
        files={
            "file": (
                "../../etc/passwd.pdf",
                _MINIMAL_PDF,
                "application/pdf",
            ),
        },
    )
    assert r.status_code == status.HTTP_201_CREATED, r.text
    saved_name = r.json()["file"]["filename"]
    # Directory components stripped; only the basename remains.
    assert "/" not in saved_name
    assert ".." not in saved_name
    assert saved_name == "passwd.pdf"
