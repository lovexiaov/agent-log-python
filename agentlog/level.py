"""Level vocabulary (language-neutral, matches Schema v1).

trace < debug < info < warn < error < critical

Levels are the six canonical values; there are no aliases. Writers must emit
one of these; readers degrade anything else to `info` at the export boundary.
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
        """
        if name not in _WEIGHTS:
            raise ValueError(
                "invalid level %r: must be one of %s" % (name, LEVELS)
            )
        return name

    @classmethod
    def from_wire(cls, name: str) -> str:
        """Return a *read-side* level name unchanged (no aliases).

        The six canonical levels are the only valid values; anything else is
        passed through so the export boundary can degrade it to `info`.
        Canonicalization for writing should use `from_name`.
        """
        return name

    @classmethod
    def is_valid(cls, name: str) -> bool:
        return name in _WEIGHTS
