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
