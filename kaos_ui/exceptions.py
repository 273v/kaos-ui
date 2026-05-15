"""Exception hierarchy for kaos-ui.

Follows the per-package pattern: a base error inheriting from
``KaosCoreError``; connectors and helpers raise subclasses; the CLI and
MCP tool layers translate them into agent-friendly messages.
"""

from __future__ import annotations

from kaos_core.exceptions import KaosCoreError


class KaosUIError(KaosCoreError):
    """Base error for kaos-ui."""


class UnknownTemplateError(KaosUIError):
    """Raised when a caller asks for a template kind that is not registered."""


class TargetExistsError(KaosUIError):
    """Raised when the scaffold target directory already exists and is not empty."""


class ScaffoldError(KaosUIError):
    """Raised on any failure during scaffold materialization."""


class PostInstallError(KaosUIError):
    """Raised when a post-install command fails."""


class DoctorError(KaosUIError):
    """Raised when doctor cannot run (not when it finds issues — those are returned, not raised)."""


# ── upload helpers (P1-5) ────────────────────────────────────────────


class UploadError(KaosUIError):
    """Base error for the ``kaos_ui.uploads`` helpers.

    Each instance carries an agent-friendly ``what / how_to_fix /
    alternative`` triple matching the kaos-* error convention so
    consumers can translate to HTTP without re-deriving the shape.
    """

    def __init__(
        self,
        *,
        what: str,
        how_to_fix: str,
        alternative: str | None = None,
    ) -> None:
        super().__init__(what)
        self.what = what
        self.how_to_fix = how_to_fix
        self.alternative = alternative


class UploadValidationError(UploadError):
    """Caller-supplied input didn't pass our validation (size, ext, name)."""


class UploadParseError(UploadError):
    """The bytes were stored but the parser refused them."""


class UploadFileNotFoundError(UploadError):
    """No such file in the session's VFS prefix.

    Named ``UploadFileNotFoundError`` rather than ``FileNotFoundError``
    so it doesn't shadow the Python builtin in callers that
    ``from kaos_ui.uploads import *``.
    """
