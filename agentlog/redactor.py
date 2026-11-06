"""Field- and content-based redaction (language-neutral, stdlib only)."""

import re

#: Default sensitive keys. Matching is case-insensitive and ignores ``_``/``-``.
#: Also matches the tail of a dotted path (e.g. ``user.email`` -> ``email``).
DEFAULT_SENSITIVE_KEYS = [
    "password",
    "passwd",
    "pwd",
    "token",
    "authorization",
    "auth",
    "cookie",
    "secret",
    "apikey",
    "api_key",
    "accesstoken",
    "access_token",
    "refreshtoken",
    "refresh_token",
    "credential",
    "privatekey",
    "private_key",
    "ssn",
    "bearer",
]

#: Replacement token written in place of any redacted value.
MASK = "***REDACTED***"

# key=value / key: value  (value may be quoted; may be a "Bearer <token>";
# stops at whitespace or query separators like '&'). Group 3 captures the value.
_KEYVAL_RE = re.compile(
    r'([A-Za-z_][A-Za-z0-9_.\-]*)\s*(=|:)\s*'
    r'(Bearer\s+[^\s&]+|"[^"]*"|\'[^\']*\'|[^\s&]+)'
)
# standalone "Bearer <token>"
_BEARER_RE = re.compile(r'Bearer\s+[A-Za-z0-9._\-]+', re.IGNORECASE)


def _norm(key: str) -> str:
    """Normalize a key for matching: lowercase, drop ``_`` and ``-``."""
    return key.lower().replace("_", "").replace("-", "")


class Redactor:
    """Mask sensitive values by key and by free-text pattern.

    Default sensitive keys are permanent (append-only): :meth:`add_paths` can
    add keys but nothing can remove the defaults. Disabling redaction entirely
    is controlled by ``enabled`` (usually driven by config ``redact_enabled``).
    """

    def __init__(self, enabled: bool = True, custom_paths=None):
        self.enabled = enabled
        # Always include the immutable defaults.
        self._paths = {_norm(k) for k in DEFAULT_SENSITIVE_KEYS}
        if custom_paths:
            for p in custom_paths:
                self.add_paths([p])

    # -- append-only API --------------------------------------------------- #
    def add_paths(self, paths):
        """APPEND sensitive key paths. Defaults can never be removed."""
        for p in paths:
            self._paths.add(_norm(p))

    # -- matching ---------------------------------------------------------- #
    def _key_matches(self, key) -> bool:
        n = _norm(key)
        if n in self._paths:
            return True
        # dotted-path tail, e.g. "user.email" -> "email"
        if "." in key:
            tail = key.rsplit(".", 1)[1]
            if _norm(tail) in self._paths:
                return True
        return False

    # -- value redaction (recursive) --------------------------------------- #
    def redact_value(self, value):
        """Recursively redact ``value`` (dict/list/str)."""
        if not self.enabled:
            return value
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                if self._key_matches(k):
                    out[k] = MASK
                else:
                    out[k] = self.redact_value(v)
            return out
        if isinstance(value, (list, tuple)):
            return [self.redact_value(v) for v in value]
        if isinstance(value, str):
            return self.redact_text(value)
        return value

    # -- free-text redaction ---------------------------------------------- #
    def redact_text(self, text):
        """Redact sensitive values embedded in free text (``key=value`` etc.)."""
        if not self.enabled:
            return text
        if not isinstance(text, str) or not text:
            return text

        def repl(m):
            key = m.group(1)
            sep = m.group(2)
            val = m.group(3)
            if self._key_matches(key):
                return "%s%s%s" % (key, sep, MASK)
            # "Authorization: Bearer xxx" already caught above; catch bare
            # Bearer-bearing values after a non-sensitive key too.
            if val.lower().startswith("bearer ") or "bearer " in val.lower():
                return "%s%s%s" % (key, sep, MASK)
            return m.group(0)

        text = _KEYVAL_RE.sub(repl, text)
        text = _BEARER_RE.sub("Bearer " + MASK, text)
        return text

    # -- top-level entry --------------------------------------------------- #
    def redact(self, message: str, payload):
        """Return ``(message, payload)`` redacted. No-op when disabled."""
        if not self.enabled:
            return message, payload
        msg = self.redact_text(message) if isinstance(message, str) else message
        pl = self.redact_value(payload) if payload is not None else None
        return msg, pl
