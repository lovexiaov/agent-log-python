"""Tests for the OTLP/HTTP exporter (transport half of D3).

A throwaway HTTP collector runs in-process on an ephemeral port so the tests
exercise the real urllib path: request shape, retry policy, and backoff.
"""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agentlog.level import Level
from agentlog.logger import Logger
from agentlog.otlp import OTLPSink, to_otlp
from agentlog.redactor import Redactor
from agentlog.otlp_http import (
    DEFAULT_OTLP_ENDPOINT,
    LOGS_PATH,
    TRACES_PATH,
    OTLPExportError,
    OTLPExporter,
    is_retryable_status,
)

TS = "2026-11-07T10:00:00.123Z"


def make_event(**overrides):
    event = {
        "ts": TS,
        "level": "info",
        "service": "com.example.demo",
        "event_type": "log",
        "session_id": "session-1",
        "agent_auto": False,
        "message": "hello",
    }
    event.update(overrides)
    return event


def network_event(**overrides):
    payload = {"method": "GET", "url": "https://api.example.com/x", "status": 200, "duration_ms": 5}
    payload.update(overrides.pop("payload", {}))
    return make_event(event_type="network_request", agent_auto=True, payload=payload, **overrides)


class _Collector:
    """Minimal OTLP/HTTP collector that records requests and scripts statuses."""

    def __init__(self, statuses=None):
        self.requests = []
        self.statuses = list(statuses or [])
        self._server = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - stdlib naming
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                outer.requests.append(
                    {
                        "path": self.path,
                        "content_type": self.headers.get("Content-Type"),
                        "headers": dict(self.headers),
                        "body": body,
                    }
                )
                status = outer._next_status()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                if status >= 400:
                    self.wfile.write(b'{"error":"boom"}')

            def log_message(self, *args):  # silence the default stderr logging
                pass

        self._handler = Handler

    def _next_status(self):
        if not self.statuses:
            return 200
        if len(self.statuses) == 1:
            return self.statuses[0]
        return self.statuses.pop(0)

    def __enter__(self):
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler)
        threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        ).start()
        return self

    def __exit__(self, *exc_info):
        self._server.shutdown()
        self._server.server_close()

    @property
    def endpoint(self):
        host, port = self._server.server_address[:2]
        return "http://%s:%d" % (host, port)


def make_logger(sink):
    return Logger(
        service="svc",
        min_level=Level.from_name("info"),
        context={},
        sink=sink,
        redactor=Redactor(enabled=True),
        session_id="session-1",
        redact_enabled=True,
        env="test",
    )


def exporter_for(collector, **kwargs):
    kwargs.setdefault("backoff", 0)
    kwargs.setdefault("sleep", lambda _delay: None)
    return OTLPExporter(collector.endpoint, **kwargs)


class RetryPolicyTest(unittest.TestCase):
    def test_retryable_status_table(self):
        for code in (408, 429, 500, 502, 503, 599):
            self.assertTrue(is_retryable_status(code), code)
        for code in (400, 401, 403, 404, 413, 422):
            self.assertFalse(is_retryable_status(code), code)

    def test_retries_then_succeeds_on_503(self):
        with _Collector(statuses=[503, 200]) as collector:
            exporter_for(collector).export_logs(to_otlp([make_event()])["logs"])
            self.assertEqual(len(collector.requests), 2, "one retry after 503")

    def test_does_not_retry_on_400(self):
        with _Collector(statuses=[400]) as collector:
            with self.assertRaises(OTLPExportError) as caught:
                exporter_for(collector).export_logs(to_otlp([make_event()])["logs"])
            self.assertEqual(len(collector.requests), 1, "4xx is permanent")
            self.assertEqual(caught.exception.status, 400)
            self.assertFalse(caught.exception.retryable)

    def test_gives_up_after_max_retries(self):
        with _Collector(statuses=[500]) as collector:  # repeats forever
            with self.assertRaises(OTLPExportError) as caught:
                exporter_for(collector, max_retries=2).export_logs(
                    to_otlp([make_event()])["logs"]
                )
            self.assertEqual(len(collector.requests), 3, "1 attempt + 2 retries")
            self.assertIn("gave up after 3 attempts", str(caught.exception))

    def test_max_retries_zero_means_single_attempt(self):
        with _Collector(statuses=[500]) as collector:
            with self.assertRaises(OTLPExportError):
                exporter_for(collector, max_retries=0).export_logs(
                    to_otlp([make_event()])["logs"]
                )
            self.assertEqual(len(collector.requests), 1)

    def test_backoff_is_exponential(self):
        delays = []
        with _Collector(statuses=[500]) as collector:
            with self.assertRaises(OTLPExportError):
                exporter_for(
                    collector, max_retries=3, backoff=0.1, sleep=delays.append
                ).export_logs(to_otlp([make_event()])["logs"])
        self.assertEqual(len(delays), 3, "one delay per retry")
        self.assertAlmostEqual(delays[0], 0.1)
        self.assertAlmostEqual(delays[1], 0.2)
        self.assertAlmostEqual(delays[2], 0.4)

    def test_backoff_is_capped(self):
        delays = []
        exporter = OTLPExporter(backoff=0.01, sleep=delays.append)
        for retry in range(1, 20):
            self.assertLessEqual(exporter._backoff_for(retry), 0.01 * 64)
        self.assertAlmostEqual(exporter._backoff_for(30), 0.01 * 64)


class RequestShapeTest(unittest.TestCase):
    def test_posts_logs_then_traces(self):
        with _Collector() as collector:
            batch = to_otlp([make_event(), network_event()])
            exporter_for(collector).export(batch)
            self.assertEqual([r["path"] for r in collector.requests], [LOGS_PATH, TRACES_PATH])
            for request in collector.requests:
                self.assertEqual(request["content_type"], "application/json")
                json.loads(request["body"].decode("utf-8"))

    def test_skips_empty_signals(self):
        with _Collector() as collector:
            exporter_for(collector).export(to_otlp([make_event()]))
            self.assertEqual([r["path"] for r in collector.requests], [LOGS_PATH])

    def test_custom_headers_are_sent(self):
        with _Collector() as collector:
            exporter_for(collector, headers={"X-Api-Key": "secret"}).export_logs(
                to_otlp([make_event()])["logs"]
            )
            self.assertEqual(collector.requests[0]["headers"].get("X-Api-Key"), "secret")

    def test_endpoint_normalization(self):
        exporter = OTLPExporter("http://collector:4318///")
        self.assertEqual(exporter._url(LOGS_PATH), "http://collector:4318/v1/logs")
        self.assertEqual(OTLPExporter("").endpoint, DEFAULT_OTLP_ENDPOINT)

    def test_transport_error_is_retryable(self):
        # Nothing listens on port 1: the connection is refused, which must be
        # treated as retryable and end in OTLPExportError, not a raw OSError.
        exporter = OTLPExporter("http://127.0.0.1:1", max_retries=1, backoff=0, sleep=lambda _d: None)
        with self.assertRaises(OTLPExportError) as caught:
            exporter.export_logs(to_otlp([make_event()])["logs"])
        self.assertTrue(caught.exception.retryable)


class SinkIntegrationTest(unittest.TestCase):
    def test_export_sink_drains_and_posts(self):
        with _Collector() as collector:
            sink = OTLPSink()
            logger = make_logger(sink)
            logger.info("one")
            logger.record_auto(
                "db_query",
                "SELECT 1",
                payload={"statement": "SELECT 1", "duration_ms": 2},
            )

            exporter_for(collector).export_sink(sink)

            self.assertEqual(len(collector.requests), 2, "logs + traces")
            self.assertEqual(len(sink), 0, "sink must be drained")

            # A second export has nothing to send and touches no socket.
            exporter_for(collector).export_sink(sink)
            self.assertEqual(len(collector.requests), 2)

    def test_redaction_is_preserved_on_the_wire(self):
        with _Collector() as collector:
            sink = OTLPSink()
            logger = make_logger(sink)
            logger.info("auth", payload={"password": "hunter2"})
            exporter_for(collector).export_sink(sink)

        body = json.loads(collector.requests[0]["body"].decode("utf-8"))
        attributes = body["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["attributes"]
        password = [kv for kv in attributes if kv["key"] == "payload.password"][0]
        self.assertNotEqual(password["value"]["stringValue"], "hunter2")


if __name__ == "__main__":
    unittest.main()
