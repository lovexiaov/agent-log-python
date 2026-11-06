"""LogEvent: the in-memory representation of one wire record.

Serialization happens only here, at the boundary, using the hand-rolled
serializer from :mod:`agentlog.json`. Top-level keys are closed: only the
reserved keys defined by Schema v1 may appear.
"""

from agentlog.json import dumps
from agentlog.coretypes import now_iso


class LogEvent:
    """A single structured log event.

    Reserved top-level fields are stored explicitly; everything else belongs in
    ``payload``. Optional fields are omitted from the wire line when empty.
    """

    # Closed set of allowed top-level keys (matches schema additionalProperties:false)
    REQUIRED = ("ts", "level", "service", "event_type", "session_id", "agent_auto", "message")
    OPTIONAL = ("subsystem", "category", "env", "user_id", "trace_id", "payload")

    def __init__(self, ts, level, service, event_type, session_id, agent_auto, message,
                 subsystem=None, category=None, env=None, user_id=None,
                 trace_id=None, payload=None):
        self.ts = ts
        self.level = level
        self.service = service
        self.event_type = event_type
        self.session_id = session_id
        self.agent_auto = agent_auto
        self.message = message
        self.subsystem = subsystem
        self.category = category
        self.env = env
        self.user_id = user_id
        self.trace_id = trace_id
        self.payload = payload

    def to_json_line(self, message=None, payload=None) -> str:
        """Serialize to a single JSONL line.

        ``message`` / ``payload`` allow the caller (Logger.emit) to pass
        already-redacted values without mutating ``self``.
        """
        if message is None:
            message = self.message
        if payload is None:
            payload = self.payload

        obj = {
            "ts": self.ts,
            "level": self.level,
            "service": self.service,
            "event_type": self.event_type,
            "session_id": self.session_id,
            "agent_auto": self.agent_auto,
            "message": message,
        }
        if self.subsystem:
            obj["subsystem"] = self.subsystem
        if self.category:
            obj["category"] = self.category
        if self.env:
            obj["env"] = self.env
        if self.user_id:
            obj["user_id"] = self.user_id
        if self.trace_id:
            obj["trace_id"] = self.trace_id
        if payload:
            obj["payload"] = payload
        return dumps(obj)
