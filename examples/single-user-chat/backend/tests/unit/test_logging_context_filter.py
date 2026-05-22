"""Unit test for the ContextFilter wire in ``app/logging_setup.py``
(audit ref: observability-operator-debug O0.1).

Pre-fix: ``app/logging_setup.py:82-99`` configured a handler +
formatter but never installed a ContextFilter; the dev-mode format
string also didn't reference ``session_id`` / ``trace_id``. Result:
SPA log records had neither attribute, dev output didn't surface
them, and any future format-string lookup would KeyError.

Post-fix: every record routed through the SPA's root handler is
guaranteed to carry both attributes (default "-") via the installed
ContextFilter, and the dev format string includes them.
"""

from __future__ import annotations

import io
import logging

import pytest

from app.logging_setup import configure
from app.settings import AppSettings


def _render_with_spa_handler(record: logging.LogRecord) -> str:
    """Apply the SPA's installed root-handler chain (Filter + Formatter)
    to a synthetic LogRecord and return the rendered output.

    pytest's ``capsys`` doesn't catch StreamHandler output because the
    handler holds a reference to ``sys.stderr`` from configure-time;
    instead, we directly drive the installed Filter + Formatter the
    same way the handler would. This is the contract the audit O0.1
    cares about: the format string must reference session_id/trace_id
    and the Filter must guarantee those attrs exist.
    """
    root_handlers = logging.getLogger().handlers
    if not root_handlers:
        return ""
    handler = root_handlers[0]
    # Run all installed filters against the record (ContextFilter
    # stamps default `-` attrs).
    for f in handler.filters:
        if not f.filter(record):
            return ""
    return handler.format(record)


@pytest.mark.unit
def test_context_filter_default_dashes() -> None:
    """A log record without explicit session_id/trace_id extras must
    still render with `-` placeholders (no AttributeError / KeyError).
    """
    settings = AppSettings(env="development", log_level="DEBUG")
    import app.logging_setup as ls

    ls._CONFIGURED = False  # type: ignore[attr-defined]
    configure(settings)

    record = logging.LogRecord(
        name="kaos.app.chat.test_unstamped",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="baseline-message",
        args=(),
        exc_info=None,
    )
    output = _render_with_spa_handler(record)
    assert "[s=- t=-]" in output, f"missing default placeholders: {output!r}"
    assert "baseline-message" in output


@pytest.mark.unit
def test_context_filter_extras_propagate() -> None:
    """When a record carries ``session_id``/``trace_id`` attrs (via
    ``extra=`` at the call site), the format string surfaces those
    values (NOT the default `-`).
    """
    settings = AppSettings(env="development", log_level="DEBUG")
    import app.logging_setup as ls

    ls._CONFIGURED = False  # type: ignore[attr-defined]
    configure(settings)

    record = logging.LogRecord(
        name="kaos.app.chat.test_stamped",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="stamped-message",
        args=(),
        exc_info=None,
    )
    # Mimic ``logger.info("...", extra={"session_id": ..., "trace_id": ...})``
    record.session_id = "01KS66KBR0"  # type: ignore[attr-defined]
    record.trace_id = "trace-abc-123"  # type: ignore[attr-defined]

    output = _render_with_spa_handler(record)
    assert "[s=01KS66KBR0 t=trace-abc-123]" in output, output
    assert "stamped-message" in output


@pytest.mark.unit
def test_context_filter_installed_on_handler() -> None:
    """The ContextFilter must be present on the SPA's root handler
    after configure(). A regression that removed the addFilter call
    would silently regress observability — this asserts the wire
    explicitly.
    """
    from kaos_core.logging import ContextFilter

    settings = AppSettings(env="development", log_level="DEBUG")
    import app.logging_setup as ls

    ls._CONFIGURED = False  # type: ignore[attr-defined]
    configure(settings)

    root_handlers = logging.getLogger().handlers
    filters_across_handlers = [f for h in root_handlers for f in h.filters]
    assert any(isinstance(f, ContextFilter) for f in filters_across_handlers), (
        "ContextFilter not installed on any root handler — observability "
        "O0.1 regression"
    )
