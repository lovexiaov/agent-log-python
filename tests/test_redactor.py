"""Tests for Redactor: default keys masked, regex on free text, recursive mask,
append-only redact."""

import unittest

from agentlog.redactor import DEFAULT_SENSITIVE_KEYS, MASK, Redactor


class RedactorTest(unittest.TestCase):
    def test_default_keys_masked_in_payload(self):
        r = Redactor(enabled=True)
        val = r.redact_value({"password": "hunter2", "token": "abc", "api_key": "xyz"})
        self.assertEqual(val["password"], MASK)
        self.assertEqual(val["token"], MASK)
        self.assertEqual(val["api_key"], MASK)

    def test_non_sensitive_passthrough(self):
        r = Redactor(enabled=True)
        val = r.redact_value({"host": "example.com", "count": 3})
        self.assertEqual(val["host"], "example.com")
        self.assertEqual(val["count"], 3)

    def test_case_insensitive_and_separators(self):
        r = Redactor(enabled=True)
        val = r.redact_value({"PassWord": "x", "ACCESS_TOKEN": "y", "api-key": "z"})
        self.assertEqual(val["PassWord"], MASK)
        self.assertEqual(val["ACCESS_TOKEN"], MASK)
        self.assertEqual(val["api-key"], MASK)

    def test_path_tail_matching(self):
        r = Redactor(enabled=True)
        val = r.redact_value({"user": {"email": "a@b.com", "password": "p"}})
        # 'password' tail masked
        self.assertEqual(val["user"]["password"], MASK)
        # 'email' is not a default sensitive key -> unchanged
        self.assertEqual(val["user"]["email"], "a@b.com")

    def test_recursive_in_lists(self):
        r = Redactor(enabled=True)
        val = r.redact_value([{"secret": "s"}, "plain", {"cookie": "c"}])
        self.assertEqual(val[0]["secret"], MASK)
        self.assertEqual(val[1], "plain")
        self.assertEqual(val[2]["cookie"], MASK)

    def test_free_text_key_value(self):
        r = Redactor(enabled=True)
        out = r.redact_text("GET /x?token=abc123&user=john")
        self.assertIn("token=%s" % MASK, out)
        self.assertIn("user=john", out)  # not sensitive

    def test_free_text_authorization_bearer(self):
        r = Redactor(enabled=True)
        out = r.redact_text("Authorization: Bearer xyz789")
        self.assertIn("Authorization", out)
        self.assertIn(MASK, out)
        self.assertNotIn("xyz789", out)

    def test_free_text_standalone_bearer(self):
        r = Redactor(enabled=True)
        out = r.redact_text("header Bearer secret-token-123")
        self.assertIn("Bearer %s" % MASK, out)

    def test_recursive_string_value_redacted(self):
        r = Redactor(enabled=True)
        val = r.redact_value({"note": "token=supersecret"})
        self.assertEqual(val["note"], "token=%s" % MASK)

    def test_append_only_cannot_remove_defaults(self):
        r = Redactor(enabled=True)
        r.add_paths(["mysecret"])
        self.assertIn("mysecret", r._paths)
        # defaults still present
        for k in DEFAULT_SENSITIVE_KEYS:
            self.assertIn(k.lower().replace("_", "").replace("-", ""), r._paths)

    def test_disabled_is_noop(self):
        r = Redactor(enabled=False)
        val = r.redact_value({"password": "hunter2"})
        self.assertEqual(val["password"], "hunter2")
        out = r.redact_text("token=abc")
        self.assertEqual(out, "token=abc")


if __name__ == "__main__":
    unittest.main()
