"""Level vocabulary (language-neutral, matches Schema v1).

trace < debug < info < warn < error < critical

`warning` is a read-only *alias* understood only on the read side; the writer
MUST never emit it. `from_wire` normalizes `warning -> warn`.
"""

#: Ordered level names, lowest weight first.
LEVELS = ["trace", "debug", "info", "warn", "error", "critical"]

#: Weight table used for min-level filtering.
_WEIGHTS = {
    "trace": 0,
    "debug": 1,
    "info": 2,
    "warn": 3,
    "error": 4,
    "critical": 5,
}


class Level:
    """Static helpers for the level vocabulary."""

    TRACE = "trace"
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    CRITICAL = "critical"

    #: read-side alias -> canonical
    _ALIASES = {"warning": "warn"}

    @classmethod
    def weight(cls, name: str) -> int:
        """Return the numeric weight of a canonical level name."""
        try:
            return _WEIGHTS[name]
        except KeyError:
            raise ValueError("unknown level: %r" % (name,))

    @classmethod
    def from_name(cls, name: str) -> str:
        """Canonicalize a *write-side* level name.

        Raises ValueError if the name is not one of the 6 canonical levels.
        `warning` is rejected here because it must never be written.
        """
        if name not in _WEIGHTS:
            raise ValueError(
                "invalid level %r: must be one of %s (warning is read-only)" % (name, LEVELS)
            )
        return name

    @classmethod
    def from_wire(cls, name: str) -> str:
        """Normalize a *read-side* level name (alias-aware).

        Accepts `warning` and maps it to `warn`. Unknown names are passed
        through unchanged so callers can decide; canonicalization for writing
        should use `from_name`.
        """
        return cls._ALIASES.get(name, name)

    @classmethod
    def is_valid(cls, name: str) -> bool:
        return name in _WEIGHTS
