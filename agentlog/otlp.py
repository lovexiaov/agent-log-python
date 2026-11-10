"""OTLP export adapter: Schema v1 event -> OpenTelemetry OTLP/JSON.

This is the D3 ("OTel alignment") capability: it does not change the wire
format, it *translates* already-emitted Schema v1 events into OTLP so they can
be shipped to the standard observability backends (Jaeger / Tempo / Loki /
Datadog / Grafana ...) through any OTLP-compatible Collector.

Mapping summary (authoritative in ``docs/logging-framework/OTLP-MAPPING.md``):

* every event            -> one OTLP ``LogRecord``
* ``network_request``    -> additionally one ``SPAN_KIND_CLIENT`` span using
                            the HTTP semantic conventions
* ``db_query``           -> additionally one ``SPAN_KIND_CLIENT`` span using
                            the Database semantic conventions
* ``crash`` / ``hang``   -> LogRecord only, with ``exception.*`` attributes
* other event types      -> LogRecord only

Design constraints:

* **Standard library only.** The package stays zero-dependency; the adapter
  produces plain ``dict``/``list`` structures (OTLP/JSON, protobuf JSON
  mapping) so callers can serialize and POST them with ``urllib``.
* **Deterministic ids.** OTLP requires a 16-byte ``trace_id`` and an 8-byte
  ``span_id`` while Schema v1 only carries an opaque ``trace_id`` string. Ids
  are therefore *derived* (SHA-256), never random: exporting the same event
  twice yields the same ids, which keeps retries and re-exports idempotent.
* **Payload is flattened one level.** ``payload`` entries become
  ``payload.<key>`` attributes; nested objects/arrays are kept as OTLP
  ``kvlistValue``/``arrayValue`` instead of being flattened further.

NOTE: some OTel semantic-convention attribute keys are still marked
*Experimental* by the specification. They are centralized in the ``_SEMCONV_*``
constants below so a future semconv revision only needs a change in one place.
"""

import datetime
import hashlib
import json
import re

from agentlog.coretypes import normalize_span_id, normalize_trace_id
from agentlog.level import Level
from agentlog.sink import Sink

#: Keep in sync with ``agentlog.__version__`` (asserted by the test suite).
SDK_VERSION = "1.4.0"

#: ``InstrumentationScope`` reported on every batch.
_SCOPE = {"name": "agentlog.otlp", "version": SDK_VERSION}

# OTLP enum values (protobuf numeric form used by OTLP/JSON).
SPAN_KIND_CLIENT = 3
STATUS_CODE_ERROR = 2

#: agent-log level -> (severityText, severityNumber).
#:
#: ``critical`` maps to FATAL, the highest level of the OTel logs model. OTel
#: numbers are spaced by 4 so implementations can express intermediate
#: severities; we only use the canonical ones.
SEVERITY = {
    "trace": ("TRACE", 1),
    "debug": ("DEBUG", 5),
    "info": ("INFO", 9),
    "warn": ("WARN", 13),
    "error": ("ERROR", 17),
    "critical": ("FATAL", 21),
}

#: OTel semantic-convention keys (stable ones first).
_SEMCONV_SERVICE_NAME = "service.name"
_SEMCONV_SERVICE_VERSION = "service.version"
_SEMCONV_DEPLOYMENT_ENV = "deployment.environment"
_SEMCONV_SESSION_ID = "session.id"
_SEMCONV_ENDUSER_ID = "enduser.id"
_SEMCONV_HTTP_METHOD = "http.request.method"
_SEMCONV_URL_FULL = "url.full"
_SEMCONV_HTTP_STATUS = "http.response.status_code"
_SEMCONV_SERVER_ADDRESS = "server.address"
_SEMCONV_DB_SYSTEM = "db.system"
_SEMCONV_DB_OPERATION = "db.operation"
_SEMCONV_DB_STATEMENT = "db.statement"
_SEMCONV_ERROR_TYPE = "error.type"
_SEMCONV_EXCEPTION_TYPE = "exception.type"
_SEMCONV_EXCEPTION_MESSAGE = "exception.message"
_SEMCONV_EXCEPTION_STACKTRACE = "exception.stacktrace"

#: agent-log specific attribute namespace (avoids colliding with semconv).
_ATTR_EVENT_TYPE = "agent.event.type"
_ATTR_AUTO = "agent.auto"
_ATTR_SUBSYSTEM = "agent.subsystem"
_ATTR_CATEGORY = "agent.category"

#: ``payload`` key -> OTLP attribute key, for the operation span only.
_HTTP_METHOD_KEYS = ("method", "http_method", "http.method")
_URL_KEYS = ("url", "url_full", "url.full")
_STATUS_KEYS = ("status_code", "status", "statusCode", "http.status_code")
_DURATION_KEYS = ("duration_ms", "durationMs", "duration")
#: The canonical SQL key is ``statement`` (unified across the six SDKs).
#: No legacy aliases: ``sql`` / ``query`` are not read.
_SQL_KEYS = ("statement",)
_DB_SYSTEM_KEYS = ("db_system", "db.system", "system")
_DB_OPERATION_KEYS = ("operation", "op")

_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})"
    r"(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$"
)


# --------------------------------------------------------------------------- #
# Input normalization
# --------------------------------------------------------------------------- #
def _as_event(event):
    """Accept a dict, a JSONL line, or a :class:`LogEvent`."""
    if isinstance(event, dict):
        return event
    if isinstance(event, str):
        return json.loads(event)
    to_json_line = getattr(event, "to_json_line", None)
    if callable(to_json_line):
        return json.loads(to_json_line())
    raise TypeError("unsupported event type: %r" % (type(event),))


# --------------------------------------------------------------------------- #
# Value / attribute conversion
# --------------------------------------------------------------------------- #
def to_any_value(value):
    """Convert a Python value to an OTLP ``AnyValue`` (proto3 JSON form).

    ``int64`` is rendered as a string, as mandated by the protobuf JSON
    mapping (JSON numbers are doubles and cannot represent 64-bit integers
    exactly).
    """
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [to_any_value(v) for v in value]}}
    if isinstance(value, dict):
        return {"kvlistValue": {"values": _key_values(value)}}
    # bytes / datetime / custom objects: fall back to their string form so a
    # stray payload value never breaks an export.
    return {"stringValue": str(value)}


def to_key_value(key, value):
    """Build one OTLP ``KeyValue``."""
    return {"key": str(key), "value": to_any_value(value)}


def _key_values(mapping, prefix=""):
    """Flatten a mapping into a list of ``KeyValue`` (``None`` skipped)."""
    out = []
    for key, value in mapping.items():
        if value is None:
            continue
        out.append(to_key_value(prefix + str(key), value))
    return out


# --------------------------------------------------------------------------- #
# Time
# --------------------------------------------------------------------------- #
def parse_timestamp_nanos(ts):
    """Parse an RFC3339 / ISO8601 timestamp into epoch nanoseconds (int).

    Sub-second precision beyond nanoseconds is truncated. A timestamp without
    an explicit offset is interpreted as UTC.
    """
    match = _TS_RE.match(str(ts).strip())
    if match is None:
        raise ValueError("not an RFC3339 timestamp: %r" % (ts,))
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    frac = match.group(7) or ""
    # Pad/truncate to nanoseconds without going through float.
    nanos = int((frac + "000000000")[:9]) if frac else 0
    offset = match.group(8)
    if offset in (None, "Z", "z"):
        tzinfo = datetime.timezone.utc
    else:
        sign = -1 if offset[0] == "-" else 1
        digits = offset[1:].replace(":", "")
        delta = datetime.timedelta(hours=int(digits[:2]), minutes=int(digits[2:4] or 0))
        tzinfo = datetime.timezone(sign * delta)
    moment = datetime.datetime(year, month, day, hour, minute, second, tzinfo=tzinfo)
    delta = moment - _EPOCH
    return (delta.days * 86400 + delta.seconds) * 1000000000 + nanos


# --------------------------------------------------------------------------- #
# Ids
# --------------------------------------------------------------------------- #
def _sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def trace_id_hex(event):
    """Return the 32-hex-char OTLP ``traceId`` for an event, or ``None``.

    Schema v1.2 constrains ``trace_id`` to 32 lowercase hex chars (uppercase
    is normalized). Non-conforming values yield ``None`` — no hashing: since
    v1.2 the write boundary drops them, so reaching this adapter they can
    only come from hand-built dicts; those are treated as trace-less too.
    """
    return normalize_trace_id(event.get("trace_id"))


def span_id_hex(event):
    """Return the 16-hex-char OTLP ``spanId`` for an event.

    Since Schema v1.1 an event may carry its own ``span_id``; when present and
    valid it is used verbatim, so the log record and the span point at the same
    real span. Otherwise the id is derived deterministically from the event
    (idempotent across retries).
    """
    explicit = normalize_span_id(event.get("span_id"))
    if explicit:
        return explicit
    seed = "|".join(
        [
            "agentlog:span",
            str(event.get("session_id", "")),
            str(event.get("trace_id") or ""),
            str(event.get("event_type", "")),
            str(event.get("ts", "")),
            str(event.get("message", "")),
        ]
    )
    return _sha256_hex(seed)[:16]


def _span_trace_id(event):
    """Trace id for a span; falls back to a per-session id when absent.

    Spans cannot exist outside a trace, so events without ``trace_id`` still
    need one. Hashing the session id keeps every span of one process in a
    single synthetic trace instead of inventing a trace per span.
    """
    resolved = trace_id_hex(event)
    if resolved:
        return resolved
    return _sha256_hex("agentlog:session:" + str(event.get("session_id", "")))[:32]


# --------------------------------------------------------------------------- #
# Level
# --------------------------------------------------------------------------- #
def level_to_severity(level):
    """Map an agent-log level to ``(severityText, severityNumber)``.

    Unknown levels (including the non-canonical ``warning``) degrade to INFO
    rather than failing the whole export.
    """
    canonical = Level.from_wire(level)
    return SEVERITY.get(canonical, SEVERITY["info"])


# --------------------------------------------------------------------------- #
# Resource / scope
# --------------------------------------------------------------------------- #
def _resource_attributes(event):
    event = _as_event(event)
    attrs = [to_key_value(_SEMCONV_SERVICE_NAME, event.get("service") or "app")]
    if event.get("env"):
        attrs.append(to_key_value(_SEMCONV_DEPLOYMENT_ENV, event["env"]))
    if event.get("release"):
        # Schema v1.3: release -> OTel service.version.
        attrs.append(to_key_value(_SEMCONV_SERVICE_VERSION, event["release"]))
    if event.get("session_id"):
        attrs.append(to_key_value(_SEMCONV_SESSION_ID, event["session_id"]))
    attrs.extend(
        [
            to_key_value("telemetry.sdk.name", "agent-log"),
            to_key_value("telemetry.sdk.language", "python"),
            to_key_value("telemetry.sdk.version", SDK_VERSION),
        ]
    )
    return attrs


def _group_by_resource(events):
    """Group events by the resource-defining fields, preserving input order."""
    groups = {}
    order = []
    for raw in events:
        event = _as_event(raw)
        key = (
            event.get("service") or "app",
            event.get("env"),
            event.get("session_id"),
        )
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(event)
    return [(key, groups[key]) for key in order]


# --------------------------------------------------------------------------- #
# LogRecord
# --------------------------------------------------------------------------- #
def event_attributes(event):
    """Translate the non-resource event fields into OTLP attributes."""
    attrs = []
    if event.get("event_type") is not None:
        attrs.append(to_key_value(_ATTR_EVENT_TYPE, event["event_type"]))
    attrs.append(to_key_value(_ATTR_AUTO, bool(event.get("agent_auto"))))
    if event.get("subsystem"):
        attrs.append(to_key_value(_ATTR_SUBSYSTEM, event["subsystem"]))
    if event.get("category"):
        attrs.append(to_key_value(_ATTR_CATEGORY, event["category"]))
    if event.get("user_id"):
        # Indirect identifier only — Schema v1 forbids direct PII here.
        attrs.append(to_key_value(_SEMCONV_ENDUSER_ID, event["user_id"]))
    payload = event.get("payload") or {}
    attrs.extend(_key_values(payload, prefix="payload."))
    # Schema v1.4：ai_error 复用 v1.3 异常词表，与 crash/hang 同样映射为 exception.*
    if event.get("event_type") in ("crash", "hang", "ai_error"):
        attrs.extend(_exception_attributes(payload))
    return attrs


def _exception_attributes(payload):
    """Map crash/hang payload onto OTel ``exception.*`` attributes."""
    attrs = []
    exc_type = payload.get("exception") or payload.get("exception_type")
    if exc_type:
        attrs.append(to_key_value(_SEMCONV_EXCEPTION_TYPE, exc_type))
    # The crash payload reuses ``message`` for the exception text; keep both
    # spellings so either SDK variant maps cleanly.
    exc_message = payload.get("exception_message") or payload.get("message")
    if exc_message:
        attrs.append(to_key_value(_SEMCONV_EXCEPTION_MESSAGE, exc_message))
    stack = payload.get("stack") or payload.get("stacktrace") or payload.get("trace")
    if stack:
        attrs.append(to_key_value(_SEMCONV_EXCEPTION_STACKTRACE, stack))
    return attrs


def event_to_log_record(event):
    """Convert one Schema v1 event into an OTLP ``LogRecord``."""
    event = _as_event(event)
    severity_text, severity_number = level_to_severity(event.get("level", "info"))
    time_nanos = str(parse_timestamp_nanos(event["ts"]))
    record = {
        "timeUnixNano": time_nanos,
        "observedTimeUnixNano": time_nanos,
        "severityNumber": severity_number,
        "severityText": severity_text,
        "body": {"stringValue": str(event.get("message") or "")},
        "attributes": event_attributes(event),
    }
    trace_id = trace_id_hex(event)
    if trace_id:
        record["traceId"] = trace_id
        # Prefer the event's own (Schema v1.1) span id — it points at a real
        # span. Otherwise only operation events get an id, matching the span
        # emitted for them, so a log record never references a missing span.
        explicit_span = normalize_span_id(event.get("span_id"))
        if explicit_span:
            record["spanId"] = explicit_span
        elif _span_kind(event) is not None:
            record["spanId"] = span_id_hex(event)
    return record


# --------------------------------------------------------------------------- #
# Spans
# --------------------------------------------------------------------------- #
def _first(payload, keys):
    for key in keys:
        if payload.get(key) not in (None, ""):
            return payload[key]
    return None


def _to_number(value):
    """Coerce a payload value to a number, **keeping float precision**.

    ``int(42.5)`` would silently truncate a sub-millisecond duration to 42 and
    make this SDK disagree with the Go/Java adapters (which both keep the
    fraction). Integer-valued strings still become ``int`` so status codes are
    emitted as ``intValue`` rather than ``doubleValue``.
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def _duration_ms(payload):
    value = _first(payload, _DURATION_KEYS)
    number = _to_number(value)
    return number if number is not None else 0


def _span_kind(event):
    """Return ``SPAN_KIND_CLIENT`` for operation events, else ``None``."""
    if event.get("event_type") in ("network_request", "db_query"):
        return SPAN_KIND_CLIENT
    return None


def _http_span(event, payload):
    method = _first(payload, _HTTP_METHOD_KEYS)
    url = _first(payload, _URL_KEYS)
    status = _to_number(_first(payload, _STATUS_KEYS))
    name = "%s %s" % (method or "HTTP", url or "")
    attrs = []
    if method:
        attrs.append(to_key_value(_SEMCONV_HTTP_METHOD, method))
    if url:
        attrs.append(to_key_value(_SEMCONV_URL_FULL, url))
        # ``server.address`` is the semconv way to expose the peer host.
        host = _host_of(url)
        if host:
            attrs.append(to_key_value(_SEMCONV_SERVER_ADDRESS, host))
    if status is not None:
        # Status codes are integers: emit intValue (not doubleValue) even when the
        # payload carried `200.0`, matching the Go/Java adapters.
        attrs.append(to_key_value(_SEMCONV_HTTP_STATUS, int(status)))
    error = None
    if status is not None and status >= 400:
        error = str(int(status))
    elif payload.get("error"):
        error = str(payload["error"])
    if error:
        attrs.append(to_key_value(_SEMCONV_ERROR_TYPE, error))
    return name, attrs, error is not None


def _host_of(url):
    match = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://([^/?#]+)", str(url))
    if match is None:
        return None
    host = match.group(1).rsplit("@", 1)[-1]
    if host.startswith("["):  # IPv6 literal
        return host.split("]")[0].lstrip("[")
    return host.split(":")[0]


def _db_span(event, payload):
    operation = _first(payload, _DB_OPERATION_KEYS)
    statement = _first(payload, _SQL_KEYS)
    system = _first(payload, _DB_SYSTEM_KEYS)
    name = "%s %s" % (operation or "SQL", statement or "")
    attrs = []
    if system:
        attrs.append(to_key_value(_SEMCONV_DB_SYSTEM, system))
    if operation:
        attrs.append(to_key_value(_SEMCONV_DB_OPERATION, operation))
    if statement:
        attrs.append(to_key_value(_SEMCONV_DB_STATEMENT, statement))
    error = payload.get("error") or payload.get("error_type")
    if error:
        attrs.append(to_key_value(_SEMCONV_ERROR_TYPE, str(error)))
    return name, attrs, bool(error)


def event_to_span(event):
    """Convert an operation event into an OTLP ``Span``, or ``None``.

    Only ``network_request`` and ``db_query`` produce spans; UI events and
    plain logs are not call spans and stay in the logs signal.
    """
    event = _as_event(event)
    kind = _span_kind(event)
    if kind is None:
        return None
    payload = event.get("payload") or {}
    if event.get("event_type") == "network_request":
        name, attrs, failed = _http_span(event, payload)
    else:
        name, attrs, failed = _db_span(event, payload)

    start = parse_timestamp_nanos(event["ts"])
    end = start + int(_duration_ms(payload) * 1000000)

    span = {
        "traceId": _span_trace_id(event),
        "spanId": span_id_hex(event),
        "name": name,
        "kind": kind,
        "startTimeUnixNano": str(start),
        "endTimeUnixNano": str(end),
        "attributes": attrs,
    }
    if failed:
        span["status"] = {"code": STATUS_CODE_ERROR, "message": name}
    return span


# --------------------------------------------------------------------------- #
# Batch builders
# --------------------------------------------------------------------------- #
def _log_scope(events):
    return {
        "scope": dict(_SCOPE),
        "logRecords": [event_to_log_record(event) for event in events],
    }


def _span_scope(events):
    spans = [span for span in (event_to_span(event) for event in events) if span]
    return {"scope": dict(_SCOPE), "spans": spans}


def _merge_extra_resource(resource, extra_resource):
    """Append ``extra_resource`` attributes, skipping keys agent-log owns.

    Duplicate keys in OTLP are allowed by the proto but resolved arbitrarily by
    backends (usually last-wins), so the spec rule "agent-log's own fields win
    on conflict" has to be enforced here by dropping the extra key entirely.
    """
    if not extra_resource:
        return resource
    taken = {kv["key"] for kv in resource}
    for kv in _key_values(extra_resource):
        if kv["key"] in taken:
            continue
        resource.append(kv)
        taken.add(kv["key"])
    return resource


def to_otlp_logs(events, extra_resource=None):
    """Build an OTLP/JSON ``ExportLogsServiceRequest`` body.

    ``extra_resource`` adds extra resource attributes to every group (e.g.
    ``{"service.version": "2.1.0"}``); agent-log's own fields win on conflict.
    """
    resource_logs = []
    for _, group in _group_by_resource(events):
        resource = _merge_extra_resource(_resource_attributes(group[0]), extra_resource)
        resource_logs.append(
            {
                "resource": {"attributes": resource},
                "scopeLogs": [_log_scope(group)],
            }
        )
    return {"resourceLogs": resource_logs}


def to_otlp_spans(events, extra_resource=None):
    """Build an OTLP/JSON ``ExportTraceServiceRequest`` body."""
    resource_spans = []
    for _, group in _group_by_resource(events):
        scope = _span_scope(group)
        if not scope["spans"]:
            continue
        resource = _merge_extra_resource(_resource_attributes(group[0]), extra_resource)
        resource_spans.append(
            {
                "resource": {"attributes": resource},
                "scopeSpans": [scope],
            }
        )
    return {"resourceSpans": resource_spans}


def to_otlp(events, extra_resource=None):
    """Build both signals for one batch of events.

    Returns ``{"logs": <ExportLogsServiceRequest>, "traces": <...>}``. OTLP
    transports one signal per request, so callers POST ``logs`` to ``/v1/logs``
    and ``traces`` to ``/v1/traces``.
    """
    events = list(events)
    return {
        "logs": to_otlp_logs(events, extra_resource),
        "traces": to_otlp_spans(events, extra_resource),
    }


def to_otlp_json(payload):
    """Serialize an OTLP payload to compact JSON (UTF-8 safe)."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


# --------------------------------------------------------------------------- #
# Sink
# --------------------------------------------------------------------------- #
class OTLPSink(Sink):
    """A sink that buffers events and renders them as OTLP batches.

    Usage::

        from agentlog import AgentLog, OTLPSink
        from agentlog.logger import Logger

        sink = OTLPSink()
        AgentLog.bootstrap(config=..., sink=sink)
        ...
        batch = sink.drain()          # {'logs': ..., 'traces': ...}
        body = to_otlp_json(batch['logs'])
        # POST body to <collector>/v1/logs with Content-Type: application/json

    The sink stores the *serialized* lines exactly as written, so redaction and
    the min-level filter have already been applied by the logger.
    """

    def __init__(self, extra_resource=None):
        self._lines = []
        self._extra_resource = dict(extra_resource or {})

    def write(self, line):
        self._lines.append(line)

    def lines(self):
        return list(self._lines)

    def export_path(self):
        return None

    def __len__(self):
        return len(self._lines)

    def drain(self):
        """Return the OTLP batch for buffered events and clear the buffer."""
        lines, self._lines = self._lines, []
        return to_otlp(lines, self._extra_resource)
