"""OTLP/HTTP exporter: send Schema v1-derived OTLP batches to a collector.

This is the transport half of D3: :mod:`agentlog.otlp` turns events into
OTLP/JSON, this module puts them on the wire (``http/json`` encoding).

Scope: deliberately small. It sends one signal per request (as OTLP requires),
retries retryable failures with exponential backoff, and does nothing else — no
batching timer, no disk buffer, no backpressure. In production point it at a
local Collector and let the Collector own durability.

Retry policy (OTLP spec guidance):

===========================================  ==========================
2xx                                          success
429 / 408 / 5xx                              retryable (exponential backoff)
other 4xx                                    permanent — the payload is
                                             malformed or unauthorised, so
                                             retrying only multiplies errors
transport error (connection refused, …)      retryable
===========================================  ==========================

Standard library only (``urllib``), keeping the package zero-dependency.
"""

import json
import time
import urllib.error
import urllib.request

#: Default OTLP/HTTP collector address (the port the OpenTelemetry Collector
#: listens on for OTLP/HTTP).
DEFAULT_OTLP_ENDPOINT = "http://localhost:4318"

LOGS_PATH = "/v1/logs"
TRACES_PATH = "/v1/traces"

DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF = 0.1

#: Retry backoff never grows beyond this multiple of ``backoff``.
_MAX_BACKOFF_SHIFT = 6


class OTLPExportError(RuntimeError):
    """Raised when a signal could not be delivered."""

    def __init__(self, message, status=None, retryable=False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def is_retryable_status(code):
    """Follow the OTLP retryable-status guidance."""
    return code in (408, 429) or code >= 500


def _is_empty_signal(payload, key):
    """True when the payload carries no resource groups (nothing to send)."""
    if not payload:
        return True
    groups = payload.get(key)
    if groups is None:
        return True
    try:
        return len(groups) == 0
    except TypeError:
        return False


class OTLPExporter:
    """Posts OTLP/JSON batches to a collector.

    Usage::

        from agentlog import AgentLog, OTLPSink, OTLPExporter

        sink = OTLPSink()
        AgentLog.bootstrap(config=..., sink=sink)
        ...
        OTLPExporter().export_sink(sink)     # drain + POST

    ``sleep`` is injectable so tests can run the retry path instantly.
    """

    def __init__(
        self,
        endpoint=DEFAULT_OTLP_ENDPOINT,
        timeout=DEFAULT_TIMEOUT,
        max_retries=DEFAULT_MAX_RETRIES,
        backoff=DEFAULT_BACKOFF,
        headers=None,
        sleep=None,
    ):
        self.endpoint = (endpoint or DEFAULT_OTLP_ENDPOINT).strip()
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.backoff = backoff
        self.headers = dict(headers or {})
        self._sleep = sleep or time.sleep

    # -- public ---------------------------------------------------------- #

    def export(self, batch):
        """Send every non-empty signal of a batch produced by ``to_otlp``.

        Logs go before traces; the first permanent error aborts the batch so the
        caller can surface it instead of silently dropping data.
        """
        if "logs" in batch:
            self.export_logs(batch["logs"])
        if "traces" in batch:
            self.export_traces(batch["traces"])

    def export_sink(self, sink):
        """Drain a sink and export the resulting batch."""
        self.export(sink.drain())

    def export_logs(self, payload):
        """POST one ExportLogsServiceRequest body (no-op when empty)."""
        return self._export_signal(payload, "resourceLogs", LOGS_PATH)

    def export_traces(self, payload):
        """POST one ExportTraceServiceRequest body (no-op when empty)."""
        return self._export_signal(payload, "resourceSpans", TRACES_PATH)

    # -- internals ------------------------------------------------------- #

    def _export_signal(self, payload, empty_key, path):
        if _is_empty_signal(payload, empty_key):
            return None
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self._post(path, body)

    def _url(self, path):
        return self.endpoint.rstrip("/") + path

    def _post(self, path, body):
        url = self._url(path)
        attempts = self.max_retries + 1
        last_error = None
        for attempt in range(attempts):
            if attempt:
                self._sleep(self._backoff_for(attempt))
            retryable, last_error = self._attempt(url, body)
            if last_error is None:
                return
            if not retryable:
                raise last_error
        raise OTLPExportError(
            "OTLP export to %s gave up after %d attempts: %s"
            % (path, attempts, last_error),
            status=getattr(last_error, "status", None),
            retryable=True,
        )

    def _attempt(self, url, body):
        """Perform one request. Returns ``(retryable, error_or_None)``."""
        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("Content-Type", "application/json")
        for key, value in self.headers.items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response.read()
            return False, None
        except urllib.error.HTTPError as exc:  # subclass of URLError: check first
            detail = ""
            try:
                detail = exc.read(512).decode("utf-8", "replace").strip()
            except Exception:  # noqa: BLE001 - the body is best-effort diagnostics
                pass
            return is_retryable_status(exc.code), OTLPExportError(
                "OTLP %s returned %d %s" % (url, exc.code, detail),
                status=exc.code,
                retryable=is_retryable_status(exc.code),
            )
        except (urllib.error.URLError, OSError) as exc:
            # Transport errors are transient: retry.
            return True, OTLPExportError("OTLP request to %s failed: %s" % (url, exc))

    def _backoff_for(self, retry):
        """Delay before the given retry (1-based): exponential, capped."""
        base = self.backoff if self.backoff and self.backoff > 0 else DEFAULT_BACKOFF
        return base * (1 << min(retry - 1, _MAX_BACKOFF_SHIFT))
