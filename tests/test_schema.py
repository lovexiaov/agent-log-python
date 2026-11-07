"""C7 SchemaTests — verify emitted JSONL conforms to Schema v1.

Uses a :class:`MemorySink` logger and a hand-rolled / stdlib validator.
No third-party JSON schema library is used; we parse emitted lines with the
standard-library :mod:`json` (allowed for test-side parsing).
"""

import json
import re
import sys
import unittest

from agentlog.agentlog import AgentLog, bootstrap, instance
from agentlog.coretypes import (
    EventType,
    get_session_id,
    install_crash_handler,
    new_session_id,
    new_trace_id,
    uninstall_crash_handler,
)
from agentlog.level import Level
from agentlog.logger import Logger
from agentlog.redactor import MASK, Redactor
from agentlog.sink import MemorySink

ALLOWED = {
    "ts", "level", "service", "event_type", "session_id", "agent_auto",
    "message", "subsystem", "category", "env", "user_id", "trace_id", "span_id",
    "payload",
}
REQUIRED = {"ts", "level", "service", "event_type", "session_id", "agent_auto", "message"}
LEVELS = {"trace", "debug", "info", "warn", "error", "critical"}
EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
RFC3339_RE = re.compile(r"T.*(Z|[+-]\d{2}:?\d{2})$")


def make_logger(min_level="info", redact_enabled=True, redact_paths=None):
    """Build a Logger writing to an in-memory sink."""
    redactor = Redactor(enabled=redact_enabled, custom_paths=redact_paths)
    sink = MemorySink()
    logger = Logger(
        service="test-svc",
        min_level=Level.from_name(min_level),
        context={},
        sink=sink,
        redactor=redactor,
        session_id="session-fixed-for-test",
        redact_enabled=redact_enabled,
        env="test",
    )
    return logger, sink


def assert_conforms(self, line):
    """Validate a single JSONL line against the Schema v1 contract."""
    L = json.loads(line)  # test-side parsing only
    # 1. dict
    self.assertIsInstance(L, dict)
    # 2. key set closed
    self.assertTrue(set(L.keys()).issubset(ALLOWED),
                    "unexpected top-level keys: %s" % (set(L.keys()) - ALLOWED))
    # 3. required present
    for k in REQUIRED:
        self.assertIn(k, L, "missing required key: %s" % k)
    # 4. level enum
    self.assertIn(L["level"], LEVELS, "bad level: %r" % L.get("level"))
    # 5. event_type pattern
    self.assertRegex(L["event_type"], EVENT_TYPE_RE, "bad event_type: %r" % L.get("event_type"))
    # 6. session_id non-empty string
    self.assertIsInstance(L["session_id"], str)
    self.assertTrue(L["session_id"], "session_id empty")
    # 7. agent_auto bool
    self.assertIsInstance(L["agent_auto"], bool)
    # 8. message str
    self.assertIsInstance(L["message"], str)
    # 9. payload is dict if present
    if "payload" in L:
        self.assertIsInstance(L["payload"], dict, "payload must be object")
    # 9b. span_id (Schema v1.1) must be 16 lowercase hex chars
    if "span_id" in L:
        self.assertRegex(L["span_id"], r"^[0-9a-f]{16}$", "bad span_id: %r" % L.get("span_id"))
    # 10. ts looks like RFC3339
    self.assertRegex(L["ts"], r"T", "ts missing 'T'")
    self.assertRegex(L["ts"], RFC3339_RE, "ts not RFC3339-like: %r" % L.get("ts"))
    return L


class SchemaTests(unittest.TestCase):
    def test_schema_conformance(self):
        logger, sink = make_logger(min_level="info", redact_enabled=True)

        # manual info with non-sensitive payload key
        logger.info("user logged in", category="auth", payload={"host": "example.com"})
        # manual warn
        logger.warn("disk almost full", payload={"host": "example.com"})
        # manual debug -> expected DROPPED at min_level=info
        logger.debug("verbose trace", payload={"host": "example.com"})
        # child logger bound context
        child = logger.child({"user_id": "u1"})
        child.info("child scoped", payload={"host": "example.com"})
        # auto event -> always logged regardless of min level
        logger.record_auto("network_request", "GET /orders -> 200",
                           payload={"host": "api.example.com", "status": 200, "duration_ms": 128})
        # log with sensitive key in payload
        logger.info("secret set", payload={"password": "hunter2", "host": "example.com"})

        lines = sink.lines()
        # 5 expected lines: info, warn, child-info, auto, sensitive-info
        # (debug was dropped by min_level=info)
        self.assertEqual(len(lines), 5, "expected 5 lines, got %d: %s" % (len(lines), lines))

        parsed = [assert_conforms(self, ln) for ln in lines]

        # locate the sensitive-info line by its message
        sensitive = next(p for p in parsed if p["message"] == "secret set")
        self.assertEqual(sensitive["payload"]["password"], MASK)
        # non-sensitive key passes through unchanged
        self.assertEqual(sensitive["payload"]["host"], "example.com")

        # locate an info line with the host payload
        info_line = next(p for p in parsed if p["message"] == "user logged in")
        self.assertEqual(info_line["payload"]["host"], "example.com")

        # child event carries user_id and parent unchanged
        child_line = next(p for p in parsed if p["message"] == "child scoped")
        self.assertEqual(child_line["user_id"], "u1")

        # auto event present at min_level=info
        auto_line = next(p for p in parsed if p["event_type"] == "network_request")
        self.assertTrue(auto_line["agent_auto"])
        self.assertEqual(auto_line["payload"]["status"], 200)

    def test_min_level_drops_manual_debug(self):
        logger, sink = make_logger(min_level="info")
        logger.debug("should be dropped")
        logger.info("should appear")
        self.assertEqual(len(sink.lines()), 1)

    def test_min_level_trace_includes_debug(self):
        logger, sink = make_logger(min_level="trace")
        logger.debug("should appear")
        logger.info("also appears")
        self.assertEqual(len(sink.lines()), 2)

    def test_auto_always_logged_regardless_of_min_level(self):
        logger, sink = make_logger(min_level="critical")  # very high threshold
        logger.debug("dropped")
        logger.info("dropped")
        logger.record_auto("crash", "boom", payload={"thread": "main"})
        lines = sink.lines()
        self.assertEqual(len(lines), 1)
        L = assert_conforms(self, lines[0])
        self.assertTrue(L["agent_auto"])
        self.assertEqual(L["event_type"], "crash")

    def test_span_id_is_emitted_when_bound(self):
        logger, sink = make_logger(min_level="info")
        child = logger.child({"span_id": "a1b2c3d4e5f60718"})
        child.info("inside span")
        L = assert_conforms(self, sink.lines()[0])
        self.assertEqual(L["span_id"], "a1b2c3d4e5f60718")

    def test_span_id_is_normalized_to_lowercase(self):
        logger, sink = make_logger(min_level="info")
        logger.child({"span_id": "A1B2C3D4E5F60718"}).info("upper span")
        L = assert_conforms(self, sink.lines()[0])
        self.assertEqual(L["span_id"], "a1b2c3d4e5f60718")

    def test_invalid_span_id_is_dropped(self):
        # A malformed span id must never produce a schema-violating line.
        logger, sink = make_logger(min_level="info")
        logger.child({"span_id": "not-a-span"}).info("bad span")
        L = assert_conforms(self, sink.lines()[0])
        self.assertNotIn("span_id", L)

    def test_trace_id_is_emitted_when_bound(self):
        logger, sink = make_logger(min_level="info")
        tid = "0123456789abcdef0123456789abcdef"
        logger.child({"trace_id": tid}).info("with trace")
        L = assert_conforms(self, sink.lines()[0])
        self.assertEqual(L["trace_id"], tid)

    def test_trace_id_is_normalized_to_lowercase(self):
        logger, sink = make_logger(min_level="info")
        logger.child({"trace_id": "0123456789ABCDEF0123456789ABCDEF"}).info("upper trace")
        L = assert_conforms(self, sink.lines()[0])
        self.assertEqual(L["trace_id"], "0123456789abcdef0123456789abcdef")

    def test_invalid_trace_id_is_dropped(self):
        # Schema v1.2: a non-hex trace_id is dropped at the write boundary;
        # the event itself is still written, just without trace context.
        logger, sink = make_logger(min_level="info")
        logger.child({"trace_id": "trace-abc"}).info("bad trace")
        L = assert_conforms(self, sink.lines()[0])
        self.assertNotIn("trace_id", L)

    def test_default_session_id_is_schema_hex(self):
        # v1.2: generated session ids are 32 lowercase hex so the natural
        # binding trace_id = session_id is always schema-valid. (The shared
        # test logger injects a fixed readable session id, so test the
        # generator directly.)
        self.assertRegex(new_session_id(), r"^[0-9a-f]{32}$")
        self.assertRegex(get_session_id(), r"^[0-9a-f]{32}$")
        self.assertRegex(new_trace_id(), r"^[0-9a-f]{32}$")

    def test_child_isolation_parent_unchanged(self):
        logger, sink = make_logger(min_level="info")
        # capture parent state
        parent_min_before = logger.min_level
        parent_ctx_before = dict(logger.context)

        child = logger.child({"user_id": "u1", "category": "tenant"})
        # child writes at its (inherited) level
        child.info("child msg")
        # mutating child must not touch parent
        child.set_level("critical")

        parent_min_after = logger.min_level
        parent_ctx_after = dict(logger.context)

        self.assertEqual(parent_min_before, parent_min_after)
        self.assertEqual(parent_ctx_before, parent_ctx_after)
        self.assertEqual(child.min_level, "critical")

        # child event has user_id; parent would not
        line = sink.lines()[0]
        L = json.loads(line)
        self.assertEqual(L["user_id"], "u1")


class CrashHandlerTest(unittest.TestCase):
    """Auto-instrumentation: uncaught exceptions become agent_auto crash events."""

    def test_crash_handler_records_auto_event(self):
        sink = MemorySink()
        bootstrap(config_json='{"service": "crash-svc"}', sink=sink)
        install_crash_handler()

        try:
            # Simulate an uncaught exception reaching the excepthook.
            raise ValueError("boom in billing")
        except ValueError:
            sys.excepthook(*sys.exc_info())

        uninstall_crash_handler()

        lines = sink.lines()
        self.assertEqual(len(lines), 1, "expected exactly one crash line")
        L = assert_conforms(self, lines[0])
        self.assertTrue(L["agent_auto"])
        self.assertEqual(L["event_type"], "crash")
        self.assertIn("boom in billing", L["message"])
        self.assertIn("payload", L)
        self.assertEqual(L["payload"]["exception"], "ValueError")
        self.assertIn("stack", L["payload"])


if __name__ == "__main__":
    unittest.main()
