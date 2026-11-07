"""Optional auto-instrumentation for third-party libraries.

These helpers stay out of the core import graph so the package remains
standard-library only. Each one is a no-op (and safe to call) when the
underlying library is not installed.
"""

import functools
import time

from agentlog.coretypes import EventType


def record_network_request(method, url, status_code, duration_ms, **extra):
    """Emit a ``network_request`` auto-event describing an HTTP call.

    This is the building block used by :func:`instrument_requests`; it can also
    be called directly when you issue requests through a client other than
    ``requests`` (e.g. ``urllib``).
    """
    payload = {
        "method": method,
        "url": url,
        "status_code": status_code,
        "duration_ms": duration_ms,
    }
    payload.update(extra)
    from agentlog.agentlog import instance

    instance().record_auto(
        EventType.NETWORK_REQUEST,
        "%s %s -> %s" % (method, url, status_code),
        category="auto",
        payload=payload,
    )


def instrument_requests(session=None):
    """Patch ``requests.Session.send`` to record ``network_request`` events.

    Idempotent: calling it twice will not double-patch. If ``requests`` is not
    installed and no custom ``session`` is supplied, this is a no-op and returns
    ``None``.

    Pass ``session=SomeSessionClass`` to patch a custom session subclass without
    requiring ``requests`` to be installed (useful for tests and adapters).
    """
    if session is None:
        try:
            import requests
        except ImportError:
            return None
        target = requests.Session
    else:
        target = session

    send = target.send
    if getattr(send, "_agentlog_patched", False):
        return target

    @functools.wraps(send)
    def patched_send(self, request, **kwargs):
        start = time.monotonic()
        resp = send(self, request, **kwargs)
        dur_ms = int((time.monotonic() - start) * 1000)
        record_network_request(
            request.method, str(request.url), resp.status_code, dur_ms
        )
        return resp

    patched_send._agentlog_patched = True
    target.send = patched_send
    return target
