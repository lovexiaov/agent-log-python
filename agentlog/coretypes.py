"""Shared core types: stable session id, event types, auto-instrumentation."""

import datetime
import threading
import traceback
import uuid
import sys


# --------------------------------------------------------------------------- #
# Session: one stable id per process
# --------------------------------------------------------------------------- #
#: A single stable session id for the whole process. Generated exactly once.
SESSION_ID = str(uuid.uuid4())


def get_session_id() -> str:
    """Return the process-wide stable session id (generated once)."""
    return SESSION_ID


def new_session_id() -> str:
    """Generate a fresh session id (used for tests / explicit resets)."""
    return str(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Timestamp helper (RFC3339 / ISO8601, millisecond precision, trailing Z)
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    """Current UTC time as ``YYYY-MM-DDThh:mm:ss.SSSZ``."""
    dt = datetime.datetime.now(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


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

    AUTO_TYPES = {SCREEN_VIEW, UI_INTERACTION, NETWORK_REQUEST, CRASH, HANG, DB_QUERY}


# --------------------------------------------------------------------------- #
# Auto-instrumentation
# --------------------------------------------------------------------------- #
_PREV_EXCEPTHOOK = None


def install_crash_handler(agentlog=None):
    """Install a :func:`sys.excepthook` that records uncaught exceptions.

    On an uncaught exception this calls ``record_auto("crash", ...)`` so the
    event is written with ``agent_auto=True`` and a payload containing
    ``thread``, ``exception`` and ``stack``.

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
            "exception": exc_type.__name__ if exc_type is not None else None,
            "stack": stack,
        }
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
