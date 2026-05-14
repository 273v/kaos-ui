"""Exception hierarchy for the Single-User Chat backend.

Per the KAOS error contract every exception carries an agent-friendly
message: what went wrong, how to fix it, and (where applicable) an
alternative.
"""

from __future__ import annotations

from kaos_core.exceptions import KaosCoreError


class AppError(KaosCoreError):
    """Base for all errors raised by this backend."""


class SettingsError(AppError):
    """A required setting is missing or invalid."""


class SessionNotFoundError(AppError):
    """Session id does not exist in our metadata sidecar."""


class UpstreamError(AppError):
    """The kaos-agents bundled API returned an unexpected error."""
