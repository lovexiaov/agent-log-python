"""Tests for the OTLP export adapter (Schema v1 -> OTLP/JSON).

Covers the mapping contract documented in
``docs/logging-framework/OTLP-MAPPING.md``: level/severity table, resource
attributes, payload flattening, deterministic ids, operation spans, and the
``OTLPSink`` integration path.
"""

import json
import unittest

import agentlog
from agentlog.coretypes import EventType
from agentlog.level import LEVELS, Level
from agentlog.logger import Logger
from agentlog.otlp import (
    SDK_VERSION,
    SPAN_KIND_CLIENT,
    STATUS_CODE_ERROR,
    OTLPSink,
    event_to_log_record,
    event_to_span,
    level_to_severity,
    parse_timestamp_nanos,
    span_id_hex,
    to_otlp,
    to_otlp_json,
    to_otlp_logs,
    to_otlp_spans,
    trace_id_hex,
)
from agentlog.redactor import Redactor

TS = "2026-11-07T10:00:00.123Z"


def make_event(**overrides):
    event = {
        "ts": TS,
        "level": "info",
        "service": "svc",
        "event_type": "log",
        "session_id": "session-1",
        "agent_auto": False,
        "message": "hello",
    }
    event.update(overrides)
    return event


def attrs_of(record_or_span):
    """Turn an OTLP ``attributes`` list into ``{key: AnyValue}``."""
    return {kv["key"]: kv["value"] for kv in record_or_span["attributes"]}


def scalar_map(record_or_span):
    """Flatten ``attributes`` into ``{key: python scalar}`` (tests only)."""
    out = {}
    for key, value in attrs_of(record_or_span).items():
        for kind in ("stringValue", "intValue", "doubleValue", "boolValue"):
            if kind in value:
                out[key] = value[kind]
                break
        else:
            out[key] = value
    return out


class LevelMappingTest(unittest.TestCase):
    def test_all_six_levels(self):
        expected = {
            "trace": ("TRACE", 1),
            "debug": ("DEBUG", 5),
            "info": ("INFO", 9),
            "warn": ("WARN", 13),
            "error": ("ERROR", 17),
            "critical": ("FATAL", 21),
        }
        for level in LEVELS:
            self.assertEqual(level_to_severity(level), expected[level], level)

    def test_warning_alias_is_normalized(self):
        # Read-side alias must map like `warn`, never like a separate level.
        self.assertEqual(level_to_severity("warning"), ("WARN", 13))

    def test_unknown_level_degrades_to_info(self):
        self.assertEqual(level_to_severity("nope"), ("INFO", 9))


class TimestampTest(unittest.TestCase):
    def test_millisecond_precision(self):
        self.assertEqual(parse_timestamp_nanos("2026-11-07T10:00:00.123Z"), 1794045600123000000)

    def test_nanosecond_precision_is_not_truncated_to_micro(self):
        self.assertEqual(parse_timestamp_nanos("2026-11-07T10:00:00.123456789Z"), 1794045600123456789)

    def test_no_fraction(self):
        self.assertEqual(parse_timestamp_nanos("2026-11-07T10:00:00Z"), 1794045600000000000)

    def test_explicit_offset(self):
        # 18:00+08:00 == 10:00Z
        self.assertEqual(
            parse_timestamp_nanos("2026-11-07T18:00:00+08:00"),
            parse_timestamp_nanos("2026-11-07T10:00:00Z"),
        )

    def test_invalid_timestamp_raises(self):
        with self.assertRaises(ValueError):
            parse_timestamp_nanos("yesterday")


class IdTest(unittest.TestCase):
    def test_hex_trace_id_used_verbatim(self):
        tid = "0123456789abcdef0123456789abcdef"
        self.assertEqual(trace_id_hex(make_event(trace_id=tid.upper())), tid)

    def test_opaque_trace_id_is_hashed_deterministically(self):
        first = trace_id_hex(make_event(trace_id="trace-abc"))
        second = trace_id_hex(make_event(trace_id="trace-abc"))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 32)
        int(first, 16)  # must be hex
        self.assertNotEqual(first, trace_id_hex(make_event(trace_id="trace-xyz")))

    def test_missing_trace_id_returns_none(self):
        self.assertIsNone(trace_id_hex(make_event()))

    def test_span_id_is_deterministic_and_8_bytes(self):
        event = make_event(event_type="network_request", payload={"method": "GET", "url": "https://x"})
        first = span_id_hex(event)
        self.assertEqual(first, span_id_hex(dict(event)))
        self.assertEqual(len(first), 16)

    def test_log_records_without_trace_have_no_ids(self):
        record = event_to_log_record(make_event())
        self.assertNotIn("traceId", record)
        self.assertNotIn("spanId", record)


class ResourceTest(unittest.TestCase):
    def test_resource_attributes(self):
        body = to_otlp_logs([make_event(env="prod")])
        resource = body["resourceLogs"][0]["resource"]["attributes"]
        attrs = {kv["key"]: kv["value"]["stringValue"] for kv in resource if "stringValue" in kv["value"]}
        self.assertEqual(attrs["service.name"], "svc")
        self.assertEqual(attrs["deployment.environment"], "prod")
        self.assertEqual(attrs["session.id"], "session-1")
        self.assertEqual(attrs["telemetry.sdk.name"], "agent-log")
        self.assertEqual(attrs["telemetry.sdk.language"], "python")

    def test_events_grouped_by_service(self):
        body = to_otlp_logs(
            [
                make_event(service="a"),
                make_event(service="b"),
                make_event(service="a"),
            ]
        )
        groups = body["resourceLogs"]
        self.assertEqual(len(groups), 2, "one resourceLogs entry per service")
        counts = sorted(len(g["scopeLogs"][0]["logRecords"]) for g in groups)
        self.assertEqual(counts, [1, 2])

    def test_extra_resource_is_merged(self):
        body = to_otlp_logs([make_event()], extra_resource={"service.version": "2.1.0"})
        keys = {kv["key"] for kv in body["resourceLogs"][0]["resource"]["attributes"]}
        self.assertIn("service.version", keys)


class LogRecordTest(unittest.TestCase):
    def test_core_fields(self):
        record = event_to_log_record(make_event(level="warn", message="disk full"))
        self.assertEqual(record["severityText"], "WARN")
        self.assertEqual(record["severityNumber"], 13)
        self.assertEqual(record["body"], {"stringValue": "disk full"})
        self.assertEqual(record["timeUnixNano"], str(parse_timestamp_nanos(TS)))
        self.assertEqual(record["observedTimeUnixNano"], record["timeUnixNano"])

    def test_agent_attributes(self):
        record = event_to_log_record(
            make_event(
                event_type="ui_interaction",
                agent_auto=True,
                subsystem="checkout",
                category="ui",
                user_id="u-1",
            )
        )
        attrs = scalar_map(record)
        self.assertEqual(attrs["agent.event.type"], "ui_interaction")
        self.assertIs(attrs["agent.auto"], True)
        self.assertEqual(attrs["agent.subsystem"], "checkout")
        self.assertEqual(attrs["agent.category"], "ui")
        self.assertEqual(attrs["enduser.id"], "u-1")

    def test_payload_is_flattened_and_typed(self):
        record = event_to_log_record(
            make_event(
                payload={
                    "count": 42,
                    "ratio": 0.5,
                    "ok": True,
                    "label": "x",
                    "nested": {"a": 1},
                    "items": [1, 2],
                    "empty": None,
                }
            )
        )
        attrs = attrs_of(record)
        self.assertEqual(attrs["payload.count"], {"intValue": "42"})
        self.assertEqual(attrs["payload.ratio"], {"doubleValue": 0.5})
        self.assertEqual(attrs["payload.ok"], {"boolValue": True})
        self.assertEqual(attrs["payload.label"], {"stringValue": "x"})
        self.assertEqual(
            attrs["payload.nested"],
            {"kvlistValue": {"values": [{"key": "a", "value": {"intValue": "1"}}]}},
        )
        self.assertEqual(
            attrs["payload.items"],
            {"arrayValue": {"values": [{"intValue": "1"}, {"intValue": "2"}]}},
        )
        self.assertNotIn("payload.empty", attrs, "None payload values are skipped")

    def test_trace_and_span_ids_present_for_operation_events(self):
        event = make_event(
            event_type="network_request",
            trace_id="0123456789abcdef0123456789abcdef",
            payload={"method": "GET", "url": "https://api.example.com/x"},
        )
        record = event_to_log_record(event)
        self.assertEqual(record["traceId"], "0123456789abcdef0123456789abcdef")
        self.assertEqual(record["spanId"], span_id_hex(event))
        span = event_to_span(event)
        self.assertEqual(span["spanId"], record["spanId"], "log record and span must share spanId")


class SpanTest(unittest.TestCase):
    def test_network_request_span(self):
        event = make_event(
            event_type="network_request",
            agent_auto=True,
            trace_id="0123456789abcdef0123456789abcdef",
            payload={
                "method": "GET",
                "url": "https://api.example.com:8443/orders?page=2",
                "status_code": 200,
                "duration_ms": 14,
            },
        )
        span = event_to_span(event)
        self.assertIsNotNone(span)
        self.assertEqual(span["kind"], SPAN_KIND_CLIENT)
        self.assertEqual(span["name"], "GET https://api.example.com:8443/orders?page=2")
        attrs = scalar_map(span)
        self.assertEqual(attrs["http.request.method"], "GET")
        self.assertEqual(attrs["url.full"], "https://api.example.com:8443/orders?page=2")
        self.assertEqual(attrs["server.address"], "api.example.com")
        self.assertEqual(attrs["http.response.status_code"], "200")
        self.assertNotIn("error.type", attrs)
        self.assertNotIn("status", span, "success spans keep status UNSET")
        # duration is expressed as the span time window
        delta = int(span["endTimeUnixNano"]) - int(span["startTimeUnixNano"])
        self.assertEqual(delta, 14 * 1000000)

    def test_error_status_sets_error_type(self):
        span = event_to_span(
            make_event(
                event_type="network_request",
                payload={"method": "POST", "url": "https://api.example.com/x", "status_code": 503},
            )
        )
        self.assertEqual(span["status"]["code"], STATUS_CODE_ERROR)
        self.assertEqual(scalar_map(span)["error.type"], "503")

    def test_db_query_span_accepts_all_payload_variants(self):
        # Go emits `query`, Java emits `sql`, the mapping doc says `statement`.
        for key in ("statement", "sql", "query"):
            span = event_to_span(
                make_event(
                    event_type=EventType.DB_QUERY,
                    agent_auto=True,
                    payload={
                        "operation": "SELECT",
                        key: "SELECT * FROM users WHERE id = ?",
                        "db_system": "postgresql",
                        "duration_ms": 3,
                    },
                )
            )
            attrs = scalar_map(span)
            self.assertEqual(attrs["db.statement"], "SELECT * FROM users WHERE id = ?", key)
            self.assertEqual(attrs["db.operation"], "SELECT", key)
            self.assertEqual(attrs["db.system"], "postgresql", key)
            self.assertNotIn("error.type", attrs, key)

    def test_db_query_error(self):
        span = event_to_span(
            make_event(
                event_type=EventType.DB_QUERY,
                payload={"operation": "INSERT", "sql": "INSERT ...", "error": "unique violation"},
            )
        )
        self.assertEqual(scalar_map(span)["error.type"], "unique violation")
        self.assertEqual(span["status"]["code"], STATUS_CODE_ERROR)

    def test_missing_duration_yields_zero_length_span(self):
        span = event_to_span(
            make_event(
                event_type="network_request",
                payload={"method": "GET", "url": "https://api.example.com/x"},
            )
        )
        self.assertEqual(span["startTimeUnixNano"], span["endTimeUnixNano"])

    def test_spans_without_trace_share_session_trace(self):
        first = event_to_span(
            make_event(event_type="network_request", payload={"method": "GET", "url": "https://a"})
        )
        second = event_to_span(
            make_event(event_type="db_query", payload={"operation": "SELECT", "sql": "SELECT 1"})
        )
        self.assertEqual(len(first["traceId"]), 32)
        self.assertEqual(first["traceId"], second["traceId"], "same session -> same synthetic trace")
        self.assertNotEqual(first["spanId"], second["spanId"])

    def test_crash_is_not_a_span(self):
        event = make_event(
            event_type="crash",
            agent_auto=True,
            level="critical",
            payload={"exception": "ValueError", "message": "boom", "stack": "Traceback ..."},
        )
        self.assertIsNone(event_to_span(event))
        record = event_to_log_record(event)
        attrs = scalar_map(record)
        self.assertEqual(attrs["exception.type"], "ValueError")
        self.assertEqual(attrs["exception.message"], "boom")
        self.assertEqual(attrs["exception.stacktrace"], "Traceback ...")
        self.assertEqual(record["severityText"], "FATAL")

    def test_plain_log_and_ui_event_have_no_span(self):
        self.assertIsNone(event_to_span(make_event()))
        self.assertIsNone(event_to_span(make_event(event_type="ui_interaction")))


class BatchTest(unittest.TestCase):
    def test_to_otlp_returns_both_signals(self):
        batch = to_otlp(
            [
                make_event(),
                make_event(
                    event_type="network_request",
                    agent_auto=True,
                    payload={"method": "GET", "url": "https://api.example.com/x", "status_code": 200},
                ),
            ]
        )
        self.assertEqual(len(batch["logs"]["resourceLogs"][0]["scopeLogs"][0]["logRecords"]), 2)
        self.assertEqual(len(batch["traces"]["resourceSpans"][0]["scopeSpans"][0]["spans"]), 1)

    def test_spans_body_lists_only_operations(self):
        body = to_otlp_spans([make_event(), make_event(event_type="ui_interaction")])
        self.assertEqual(body, {"resourceSpans": []})

    def test_to_otlp_json_is_parsable(self):
        body = to_otlp_logs([make_event(payload={"host": "example.com"})])
        parsed = json.loads(to_otlp_json(body))
        self.assertEqual(parsed["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["body"], {"stringValue": "hello"})


class OTLPSinkTest(unittest.TestCase):
    def _logger(self, sink):
        return Logger(
            service="sink-svc",
            min_level=Level.from_name("info"),
            context={},
            sink=sink,
            redactor=Redactor(enabled=True),
            session_id="sink-session",
            redact_enabled=True,
            env="test",
        )

    def test_sink_buffers_and_drains(self):
        sink = OTLPSink()
        logger = self._logger(sink)
        logger.info("first")
        logger.record_auto(EventType.NETWORK_REQUEST, "GET https://api.example.com/x -> 200",
                           payload={"method": "GET", "url": "https://api.example.com/x",
                                    "status_code": 200, "duration_ms": 7})
        self.assertEqual(len(sink), 2)

        batch = sink.drain()
        records = batch["logs"]["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
        self.assertEqual(len(records), 2)
        spans = batch["traces"]["resourceSpans"][0]["scopeSpans"][0]["spans"]
        self.assertEqual(len(spans), 1)
        self.assertEqual(len(sink), 0, "drain() clears the buffer")

    def test_sink_output_preserves_redaction(self):
        sink = OTLPSink()
        logger = self._logger(sink)
        logger.info("login", payload={"password": "hunter2"})
        batch = sink.drain()
        record = batch["logs"]["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        body = record["body"]["stringValue"]
        values = json.dumps(scalar_map(record))
        self.assertNotIn("hunter2", values + body)

    def test_sink_extra_resource(self):
        sink = OTLPSink(extra_resource={"service.version": "9.9.9"})
        logger = self._logger(sink)
        logger.info("x")
        batch = sink.drain()
        keys = {kv["key"] for kv in batch["logs"]["resourceLogs"][0]["resource"]["attributes"]}
        self.assertIn("service.version", keys)


class VersionTest(unittest.TestCase):
    def test_sdk_version_matches_package_version(self):
        self.assertEqual(SDK_VERSION, agentlog.__version__, "keep SDK_VERSION in sync with __version__")


if __name__ == "__main__":
    unittest.main()
