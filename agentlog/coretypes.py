"""Shared core types: stable session id, event types, auto-instrumentation."""

import datetime
import re
import threading
import traceback
import uuid
import sys


# --------------------------------------------------------------------------- #
# Session: one stable id per process
# --------------------------------------------------------------------------- #
#: A single stable session id for the whole process. Generated exactly once.
#: 32 lowercase hex chars, so ``trace_id = session_id`` is always Schema-valid.
SESSION_ID = uuid.uuid4().hex


def get_session_id() -> str:
    """Return the process-wide stable session id (generated once)."""
    return SESSION_ID


def new_session_id() -> str:
    """Generate a fresh session id (used for tests / explicit resets)."""
    return uuid.uuid4().hex


# --------------------------------------------------------------------------- #
# Trace id (Schema v1.2): 32 lowercase hex chars = 8 bytes, same shape as the
# W3C traceparent trace-id and the OTLP traceId.
# --------------------------------------------------------------------------- #
_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def new_trace_id() -> str:
    """Generate a fresh Schema-valid trace id (uuid4 without hyphens)."""
    return uuid.uuid4().hex


def is_valid_trace_id(value) -> bool:
    """Return True if ``value`` is a Schema v1.2 ``trace_id``."""
    return isinstance(value, str) and _TRACE_ID_RE.match(value) is not None


def normalize_trace_id(value):
    """Render ``value`` as a canonical lowercase trace id, or ``None``.

    Uppercase hex is accepted and lowercased. Anything else yields ``None``:
    a bad trace id must never make an event un-serializable or violate the
    schema — the field is dropped and the event is written without trace
    context (same policy as ``span_id``).
    """
    if not isinstance(value, str):
        return None
    lowered = value.lower()
    return lowered if _TRACE_ID_RE.match(lowered) else None


# --------------------------------------------------------------------------- #
# Timestamp helper (RFC3339 / ISO8601, millisecond precision, trailing Z)
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    """Current UTC time as ``YYYY-MM-DDThh:mm:ss.SSSZ``."""
    dt = datetime.datetime.now(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


# --------------------------------------------------------------------------- #
# Span id (Schema v1.1, optional)
# --------------------------------------------------------------------------- #
#: 16 lowercase hex chars = 8 bytes, same shape as the W3C traceparent span-id.
_SPAN_ID_RE = re.compile(r"^[0-9a-f]{16}$")


def is_valid_span_id(value) -> bool:
    """Return True if ``value`` is a Schema v1.1 ``span_id``."""
    return isinstance(value, str) and _SPAN_ID_RE.match(value) is not None


def normalize_span_id(value):
    """Render ``value`` as a canonical lowercase span id, or ``None``.

    Non-conforming values are reported as ``None`` instead of raising: a bad
    span id must never make an event un-serializable or violate the schema.
    """
    if not isinstance(value, str):
        return None
    lowered = value.lower()
    return lowered if _SPAN_ID_RE.match(lowered) else None


# --------------------------------------------------------------------------- #
# EventType
# --------------------------------------------------------------------------- #
class EventType:
    """Canonical ``event_type`` strings (snake_case, matches Schema v1)."""

    # automatic instrumentation
    SCREEN_VIEW = "screen_view"
    UI_INTERACTION = "ui_interaction"
    NETWORK_REQUEST = "network_request"
    CRASH = "crash"
    HANG = "hang"
    DB_QUERY = "db_query"

    # manual logging
    LOG = "log"

    # AI interaction events (Schema v1.4)
    AI_REQUEST_INITIATED = "ai_request_initiated"
    AI_RESPONSE_RECEIVED = "ai_response_received"
    AI_TOOL_CALL_INITIATED = "ai_tool_call_initiated"
    AI_TOOL_CALL_COMPLETED = "ai_tool_call_completed"
    AI_GUARDRAIL_TRIGGERED = "ai_guardrail_triggered"
    AI_ERROR = "ai_error"

    AUTO_TYPES = {SCREEN_VIEW, UI_INTERACTION, NETWORK_REQUEST, CRASH, HANG, DB_QUERY}
    AI_TYPES = {
        AI_REQUEST_INITIATED, AI_RESPONSE_RECEIVED, AI_TOOL_CALL_INITIATED,
        AI_TOOL_CALL_COMPLETED, AI_GUARDRAIL_TRIGGERED, AI_ERROR,
    }


# --------------------------------------------------------------------------- #
# Auto-instrumentation
# --------------------------------------------------------------------------- #
_PREV_EXCEPTHOOK = None


def install_crash_handler(agentlog=None):
    """Install a :func:`sys.excepthook` that records uncaught exceptions.

    On an uncaught exception this calls ``record_auto("crash", ...)`` so the
    event is written with ``agent_auto=True`` and a payload containing the
    standard exception vocabulary (``exception`` / ``exception_message`` /
    ``stack`` / ``mechanism``) plus ``thread``.

    The previous excepthook (if any) is preserved and invoked afterwards so
    behavior of other hooks is not broken.
    """
    global _PREV_EXCEPTHOOK

    def hook(exc_type, exc_value, exc_tb):
        stack = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        message = "crash: %s" % (exc_value if exc_value is not None else
                                 (exc_type.__name__ if exc_type else "unknown"))
        payload = {
            "thread": threading.current_thread().name,
            "stack": stack,
            "mechanism": "uncaught",
        }
        if exc_type is not None:
            payload["exception"] = exc_type.__name__
        if exc_value is not None:
            payload["exception_message"] = str(exc_value)
        try:
            alog = agentlog
            if alog is None:
                # Lazy import to avoid a circular import at module load time.
                from agentlog.agentlog import instance
                alog = instance()
            alog.record_auto(EventType.CRASH, message, category="auto", payload=payload)
        except Exception:
            # Never let the hook itself crash the interpreter.
            pass
        if _PREV_EXCEPTHOOK is not None:
            _PREV_EXCEPTHOOK(exc_type, exc_value, exc_tb)

    _PREV_EXCEPTHOOK = sys.excepthook
    sys.excepthook = hook


def uninstall_crash_handler():
    """Restore the previous excepthook (primarily for tests)."""
    global _PREV_EXCEPTHOOK
    if _PREV_EXCEPTHOOK is not None:
        sys.excepthook = _PREV_EXCEPTHOOK
        _PREV_EXCEPTHOOK = None
