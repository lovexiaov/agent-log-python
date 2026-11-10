"""AgentLog — language-neutral structured logging for Python (Schema v1).

Standard-library only. Wire format conforms to
``docs/schema/log-event.schema.json`` (additionalProperties: false).

Quick start::

    from agentlog import AgentLog, Level

    AgentLog.bootstrap(config_json='{"service": "my-app"}')
    AgentLog.info("hello", payload={"host": "example.com"})
"""

from agentlog.agentlog import (
    bootstrap,
    child,
    critical,
    debug,
    error,
    export_path,
    info,
    instance,
    record_auto,
    redact,
    set_level,
    trace,
    warn,
    warning,
)
from agentlog.config import LoggingConfig
from agentlog.coretypes import (
    EventType,
    get_session_id,
    install_crash_handler,
    new_trace_id,
)
from agentlog.instrumentation import instrument_requests, record_network_request
from agentlog.json import dumps, loads
from agentlog.level import Level
from agentlog.logger import Logger
from agentlog.logevent import LogEvent
from agentlog.otlp import (
    OTLPSink,
    event_to_log_record,
    event_to_span,
    level_to_severity,
    parse_timestamp_nanos,
    to_otlp,
    to_otlp_json,
    to_otlp_logs,
    to_otlp_spans,
    trace_id_hex,
)
from agentlog.otlp_http import (
    DEFAULT_OTLP_ENDPOINT,
    OTLPExportError,
    OTLPExporter,
)
from agentlog.redactor import DEFAULT_SENSITIVE_KEYS, MASK, Redactor
from agentlog.sink import FileSink, MemorySink, Sink

# Public facade: the process-wide singleton instance, so that
# ``AgentLog.bootstrap(...)`` and ``AgentLog.info(...)`` behave as documented.
AgentLog = instance()

__all__ = [
    "AgentLog",
    "Logger",
    "Level",
    "EventType",
    "LogEvent",
    "LoggingConfig",
    "Redactor",
    "DEFAULT_SENSITIVE_KEYS",
    "MASK",
    "Sink",
    "FileSink",
    "MemorySink",
    "OTLPSink",
    "OTLPExporter",
    "OTLPExportError",
    "DEFAULT_OTLP_ENDPOINT",
    "to_otlp",
    "to_otlp_json",
    "to_otlp_logs",
    "to_otlp_spans",
    "event_to_log_record",
    "event_to_span",
    "level_to_severity",
    "parse_timestamp_nanos",
    "trace_id_hex",
    "dumps",
    "loads",
    "install_crash_handler",
    "get_session_id",
    "instrument_requests",
    "record_network_request",
    # facade convenience
    "bootstrap",
    "instance",
    "new_trace_id",
    "info",
    "warn",
    "warning",
    "error",
    "debug",
    "trace",
    "critical",
    "record_auto",
    "child",
    "set_level",
    "redact",
    "export_path",
]

__version__ = "1.3.0"
