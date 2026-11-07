"""Logger: the core emit/child/set_level/redact engine."""

from agentlog.coretypes import EventType, get_session_id, now_iso
from agentlog.level import Level
from agentlog.logevent import LogEvent
from agentlog.redactor import Redactor

# Reserved top-level context keys mapped from (possibly camelCase) input.
# session_id is deliberately NOT overridable via child(): it stays stable
# for the whole process.
_CONTEXT_STRINGS = ("subsystem", "category", "env", "user_id", "trace_id", "span_id")


def _normalize_key(key: str) -> str:
    """Map a possibly-camelCase context key to its snake_case reserved form."""
    mapping = {
        "subsystem": "subsystem",
        "category": "category",
        "env": "env",
        "userid": "user_id",
        "user_id": "user_id",
        "traceid": "trace_id",
        "trace_id": "trace_id",
        "spanid": "span_id",
        "span_id": "span_id",
        "sessionid": "session_id",
        "session_id": "session_id",
    }
    return mapping.get(key.lower().replace("-", "_"), key)


class Logger:
    """A logger bound to a service, level, sink, redactor and scope context."""

    def __init__(self, service, min_level, context, sink, redactor, session_id,
                 redact_enabled, env=None):
        self.service = service
        self.min_level = min_level  # canonical level string (min threshold)
        self.context = dict(context)  # bound scope fields
        self.sink = sink
        self.redactor = redactor  # shared (append-only) instance
        self.session_id = session_id
        self.redact_enabled = redact_enabled
        self.env = env

    # -- configuration ---------------------------------------------------- #
    def set_level(self, level: str) -> None:
        self.min_level = Level.from_name(level)

    def redact(self, paths) -> None:
        """Append sensitive paths (append-only; defaults survive)."""
        self.redactor.add_paths(paths)

    # -- child (immutable parent) ----------------------------------------- #
    def child(self, context: dict) -> "Logger":
        """Return a NEW logger merging ``context`` into the bound scope.

        The parent logger is never mutated.
        """
        new_ctx = dict(self.context)
        for k, v in context.items():
            key = _normalize_key(k)
            # Never let a child overwrite the stable session_id.
            if key == "session_id":
                continue
            new_ctx[key] = v
        return Logger(
            service=self.service,
            min_level=self.min_level,
            context=new_ctx,
            sink=self.sink,
            redactor=self.redactor,
            session_id=self.session_id,
            redact_enabled=self.redact_enabled,
            env=self.env,
        )

    # -- event construction ------------------------------------------------ #
    def _build_event(self, level, event_type, message, category, trace_id, payload,
                     agent_auto):
        ctx = self.context
        return LogEvent(
            ts=now_iso(),
            level=level,
            service=self.service,
            event_type=event_type,
            session_id=self.session_id,
            agent_auto=agent_auto,
            message=message,
            subsystem=ctx.get("subsystem"),
            category=category if category is not None else ctx.get("category"),
            env=self.env if self.env is not None else ctx.get("env"),
            user_id=ctx.get("user_id"),
            trace_id=trace_id if trace_id is not None else ctx.get("trace_id"),
            payload=payload,
            span_id=ctx.get("span_id"),
        )

    # -- emit -------------------------------------------------------------- #
    def emit(self, event: LogEvent) -> None:
        """Filter (manual only), redact, and write the event as JSONL."""
        if not event.agent_auto:
            if Level.weight(event.level) < Level.weight(self.min_level):
                return  # dropped by min-level filter
        message = event.message
        payload = event.payload
        if self.redact_enabled:
            message, payload = self.redactor.redact(message, payload)
        self.sink.write(event.to_json_line(message=message, payload=payload))

    # -- manual convenience (agent_auto=False) ----------------------------- #
    def trace(self, message, category="app", trace_id=None, payload=None):
        self._manual("trace", message, category, trace_id, payload)

    def debug(self, message, category="app", trace_id=None, payload=None):
        self._manual("debug", message, category, trace_id, payload)

    def info(self, message, category="app", trace_id=None, payload=None):
        self._manual("info", message, category, trace_id, payload)

    def warn(self, message, category="app", trace_id=None, payload=None):
        self._manual("warn", message, category, trace_id, payload)

    def error(self, message, category="app", trace_id=None, payload=None):
        self._manual("error", message, category, trace_id, payload)

    def critical(self, message, category="app", trace_id=None, payload=None):
        self._manual("critical", message, category, trace_id, payload)

    def _manual(self, level, message, category, trace_id, payload):
        evt = self._build_event(level, EventType.LOG, message, category, trace_id,
                                payload, agent_auto=False)
        self.emit(evt)

    # -- automatic instrumentation (agent_auto=True) ----------------------- #
    def record_auto(self, event_type, message, category="auto", trace_id=None, payload=None):
        evt = self._build_event("info", event_type, message, category, trace_id,
                                payload, agent_auto=True)
        self.emit(evt)

    def export_path(self):
        return self.sink.export_path()
