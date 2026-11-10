"""Tests for AI interaction events (Schema v1.4).

Mirrors the Web/OTLP standardization: AI events use canonical event_type values
and a snake_case payload vocabulary, with agent_auto=False.
"""

import json
import unittest

from agentlog import (
    bootstrap,
    record_ai_request,
    record_ai_response,
    record_ai_tool_call,
    record_ai_tool_result,
    record_ai_guardrail,
    record_ai_error,
)
from agentlog.sink import MemorySink


class AiEventTest(unittest.TestCase):
    def setUp(self):
        self.sink = MemorySink()
        bootstrap(sink=self.sink)

    def _last(self):
        return json.loads(self.sink.lines()[-1])

    def test_request(self):
        record_ai_request("gpt-4o", "summarize this")
        L = self._last()
        self.assertEqual(L["event_type"], "ai_request_initiated")
        self.assertEqual(L["level"], "info")
        self.assertFalse(L["agent_auto"])
        self.assertEqual(L["payload"]["model"], "gpt-4o")
        self.assertEqual(L["payload"]["prompt_text"], "summarize this")
        self.assertNotIn("promptText", L["payload"])

    def test_response_tokens(self):
        record_ai_response(
            "gpt-4o", total_tokens=530, prompt_tokens=320,
            completion_tokens=210, request_id="r1",
        )
        L = self._last()
        self.assertEqual(L["event_type"], "ai_response_received")
        p = L["payload"]
        self.assertEqual(p["total_tokens"], 530)
        self.assertEqual(p["prompt_tokens"], 320)
        self.assertEqual(p["completion_tokens"], 210)
        self.assertEqual(p["request_id"], "r1")

    def test_tool_call_and_result(self):
        record_ai_tool_call("search", {"q": "x"})
        L = self._last()
        self.assertEqual(L["event_type"], "ai_tool_call_initiated")
        self.assertEqual(L["payload"]["tool_name"], "search")
        record_ai_tool_result("search", True, tool_call_latency_ms=12)
        L = self._last()
        self.assertEqual(L["event_type"], "ai_tool_call_completed")
        self.assertTrue(L["payload"]["ok"])

    def test_guardrail_warn(self):
        record_ai_guardrail("toxicity", "blocked")
        L = self._last()
        self.assertEqual(L["event_type"], "ai_guardrail_triggered")
        self.assertEqual(L["level"], "warn")
        self.assertEqual(L["payload"]["guardrail_type"], "toxicity")

    def test_error_uses_exception_vocab(self):
        record_ai_error("RateLimitError", "429 too many requests", request_id="r9")
        L = self._last()
        self.assertEqual(L["event_type"], "ai_error")
        self.assertEqual(L["level"], "error")
        self.assertFalse(L["agent_auto"])
        p = L["payload"]
        self.assertEqual(p["exception"], "RateLimitError")
        self.assertEqual(p["exception_message"], "429 too many requests")
        self.assertEqual(p["mechanism"], "handled")

    def test_no_camelcase_payload_keys(self):
        record_ai_response("gpt-4o", total_tokens=10)
        L = self._last()
        for key in L["payload"].keys():
            self.assertFalse(
                any(c.isupper() for c in key),
                "payload key %r is not snake_case" % key,
            )

    def test_extra_keys_allowed_in_payload(self):
        record_ai_response("gpt-4o", total_tokens=10, custom_field="ok")
        L = self._last()
        self.assertEqual(L["payload"]["custom_field"], "ok")


if __name__ == "__main__":
    unittest.main()
