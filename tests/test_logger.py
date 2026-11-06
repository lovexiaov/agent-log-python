"""Tests for Logger: child isolation, set_level filtering, context propagation."""

import unittest

from agentlog.level import Level
from agentlog.logger import Logger
from agentlog.redactor import Redactor
from agentlog.sink import MemorySink


def make_logger(min_level="info"):
    sink = MemorySink()
    redactor = Redactor(enabled=True)
    logger = Logger(
        service="svc",
        min_level=Level.from_name(min_level),
        context={},
        sink=sink,
        redactor=redactor,
        session_id="fixed-session",
        redact_enabled=True,
        env="prod",
    )
    return logger, sink


class LoggerTest(unittest.TestCase):
    def test_child_does_not_mutate_parent(self):
        logger, _ = make_logger()
        child = logger.child({"user_id": "u1"})
        child.info("hi")
        # parent context unaffected
        self.assertNotIn("user_id", logger.context)
        self.assertIn("user_id", child.context)

    def test_child_merges_context(self):
        logger, sink = make_logger()
        child = logger.child({"user_id": "u1", "subsystem": "sub.a"})
        child.info("scoped")
        L = __import__("json").loads(sink.lines()[0])
        self.assertEqual(L["user_id"], "u1")
        self.assertEqual(L["subsystem"], "sub.a")
        self.assertEqual(L["env"], "prod")  # inherited env

    def test_child_cannot_override_session_id(self):
        logger, sink = make_logger()
        child = logger.child({"session_id": "should-be-ignored"})
        child.info("x")
        L = __import__("json").loads(sink.lines()[0])
        self.assertEqual(L["session_id"], "fixed-session")

    def test_set_level_filters_manual_only(self):
        logger, sink = make_logger(min_level="warn")
        logger.debug("drop")
        logger.info("drop")
        logger.warn("keep")
        logger.error("keep")
        self.assertEqual(len(sink.lines()), 2)

    def test_set_level_runtime(self):
        logger, sink = make_logger(min_level="info")
        logger.debug("drop")
        self.assertEqual(len(sink.lines()), 0)
        logger.set_level("debug")
        logger.debug("keep")
        self.assertEqual(len(sink.lines()), 1)

    def test_level_normalization_rejects_warning_on_write(self):
        logger, _ = make_logger()
        with self.assertRaises(ValueError):
            logger.set_level("warning")

    def test_manual_event_type_is_log(self):
        logger, sink = make_logger()
        logger.info("msg")
        L = __import__("json").loads(sink.lines()[0])
        self.assertEqual(L["event_type"], "log")
        self.assertFalse(L["agent_auto"])

    def test_auto_event_type_and_flag(self):
        logger, sink = make_logger(min_level="critical")
        logger.record_auto("hang", "frozen")
        L = __import__("json").loads(sink.lines()[0])
        self.assertEqual(L["event_type"], "hang")
        self.assertTrue(L["agent_auto"])
        self.assertEqual(L["level"], "info")


if __name__ == "__main__":
    unittest.main()
