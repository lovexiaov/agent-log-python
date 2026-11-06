"""Tests for LoggingConfig.from_json (hand-rolled parser, defaults + override)."""

import json
import os
import tempfile
import unittest

from agentlog.config import LoggingConfig


class ConfigTest(unittest.TestCase):
    def test_defaults(self):
        cfg = LoggingConfig.from_json("{}")
        self.assertEqual(cfg.service, "app")
        self.assertIsNone(cfg.env)
        self.assertEqual(cfg.level, "info")
        self.assertTrue(cfg.redact_enabled)
        self.assertEqual(cfg.redact_paths, [])

    def test_service_required_nonempty(self):
        cfg = LoggingConfig.from_json('{"service": ""}')
        self.assertEqual(cfg.service, "app")  # empty -> default
        cfg2 = LoggingConfig.from_json('{"service": "web-api"}')
        self.assertEqual(cfg2.service, "web-api")

    def test_override_all(self):
        text = json.dumps({
            "service": "my-svc",
            "env": "staging",
            "level": "debug",
            "redact_enabled": False,
            "redact_paths": ["custom_secret"],
            "export_directory": "/tmp/x",
        })
        cfg = LoggingConfig.from_json(text)
        self.assertEqual(cfg.service, "my-svc")
        self.assertEqual(cfg.env, "staging")
        self.assertEqual(cfg.level, "debug")
        self.assertFalse(cfg.redact_enabled)
        self.assertEqual(cfg.redact_paths, ["custom_secret"])
        self.assertEqual(cfg.export_directory, "/tmp/x")

    def test_warning_alias_normalized(self):
        # "warning" read alias maps to "warn" on the wire
        cfg = LoggingConfig.from_json('{"level": "warning"}')
        self.assertEqual(cfg.level, "warn")

    def test_invalid_level_falls_back(self):
        cfg = LoggingConfig.from_json('{"level": "verbose"}')
        self.assertEqual(cfg.level, "info")

    def test_export_directory_default_is_tempdir(self):
        cfg = LoggingConfig.from_json("{}")
        self.assertTrue(cfg.export_directory.endswith("agent-log"))
        self.assertTrue(os.path.join(tempfile.gettempdir(), "agent-log").startswith("/"))


if __name__ == "__main__":
    unittest.main()
