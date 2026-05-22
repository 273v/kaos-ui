"""Logging setup — JSON in production, human in dev.

Uses ``kaos_core.logging.get_logger`` so logger names are auto-prefixed
under ``kaos.app.chat.*`` and ``session_id`` / ``trace_id`` propagate
when a ``KaosContext`` is in scope.

CWE-117 defense: every formatter strips embedded CR/LF from message
text and from extra-keyed values before emission.
"""

from __future__ import annotations

import json
import logging
import sys

from kaos_core.logging import get_logger

from app.settings import AppSettings

_CONFIGURED = False

_RESERVED_LOGRECORD_KEYS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


def _strip_crlf(value: object) -> object:
    if isinstance(value, str):
        return value.replace("\r", "\\r").replace("\n", "\\n")
    return value


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "msg": _strip_crlf(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOGRECORD_KEYS or key.startswith("_"):
                continue
            payload[key] = _strip_crlf(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class _HumanFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.msg = _strip_crlf(record.getMessage())
        record.args = ()
        return super().format(record)


def configure(settings: AppSettings) -> None:
    """Idempotent. Call once at startup."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stderr)
    if settings.env == "production":
        handler.setFormatter(_JsonFormatter())
    else:
        # Include session_id + trace_id in the dev format so
        # ContextFilter-stamped records surface them. Records without
        # these attributes (most stdlib + uvicorn logs) get the
        # placeholder `-` from ContextFilter — no AttributeError.
        # Audit ref: observability-operator-debug O0.1 — the
        # `[session=- trace=-]` propagation contract.
        handler.setFormatter(
            _HumanFormatter(
                "%(asctime)s %(levelname)-7s %(name)s "
                "[s=%(session_id)s t=%(trace_id)s] %(message)s"
            )
        )
    # #observability O0.1 — install ContextFilter so every log record
    # carries `session_id` + `trace_id` attributes (defaulting to "-").
    # Without this filter the format-string lookup raises KeyError on
    # records that don't pass extras, and the previous behavior was
    # silently dropping these fields. kaos_core's ContextFilter is the
    # source of truth; we install it on the SPA's root handler so the
    # filter applies to every log record going through the SPA's
    # stream (kaos.* logs use the kaos_core handler in addition).
    from kaos_core.logging import ContextFilter

    handler.addFilter(ContextFilter())
    root.addHandler(handler)
    _CONFIGURED = True


def app_logger(suffix: str) -> logging.Logger:
    """``app_logger("chat")`` → ``kaos.app.chat.chat``."""
    return get_logger(f"kaos.app.chat.{suffix}")
