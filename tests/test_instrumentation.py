import json
import unittest

from agentlog import AgentLog, MemorySink
from agentlog import record_network_request, instrument_requests


class FakeRequest:
    def __init__(self, method, url):
        self.method = method
        self.url = url


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeSession:
    _agentlog_patched = False

    def __init__(self):
        self.calls = []

    def send(self, request, **kwargs):
        self.calls.append(request)
        return FakeResponse(204)


class NetworkRequestTests(unittest.TestCase):
    def test_record_network_request(self):
        sink = MemorySink()
        AgentLog.bootstrap(sink=sink)
        record_network_request("GET", "http://example.com/api", 200, 12)

        self.assertEqual(len(sink.lines()), 1)
        evt = json.loads(sink.lines()[0])
        self.assertEqual(evt["event_type"], "network_request")
        self.assertTrue(evt["agent_auto"])
        self.assertEqual(evt["level"], "info")
        payload = evt["payload"]
        self.assertEqual(payload["method"], "GET")
        self.assertEqual(payload["url"], "http://example.com/api")
        self.assertEqual(payload["status_code"], 200)
        self.assertEqual(payload["duration_ms"], 12)

    def test_instrument_requests_patching(self):
        returned = instrument_requests(session=FakeSession)
        self.assertIs(returned, FakeSession)
        self.assertTrue(getattr(FakeSession.send, "_agentlog_patched", False))

        sink = MemorySink()
        AgentLog.bootstrap(sink=sink)

        sess = FakeSession()
        resp = sess.send(FakeRequest("POST", "http://example.com/x"))
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(len(sess.calls), 1)

        events = [json.loads(l) for l in sink.lines()]
        net = [e for e in events if e["event_type"] == "network_request"]
        self.assertEqual(len(net), 1)
        self.assertEqual(net[0]["payload"]["method"], "POST")
        self.assertEqual(net[0]["payload"]["status_code"], 204)

    def test_instrument_requests_idempotent(self):
        instrument_requests(session=FakeSession)
        sink = MemorySink()
        AgentLog.bootstrap(sink=sink)
        sess = FakeSession()
        sess.send(FakeRequest("GET", "http://x"))
        net = [
            e
            for e in (json.loads(l) for l in sink.lines())
            if e["event_type"] == "network_request"
        ]
        self.assertEqual(len(net), 1, "re-patching must not double-record")


if __name__ == "__main__":
    unittest.main()
