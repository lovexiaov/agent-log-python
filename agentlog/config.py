"""Language-neutral logging configuration.

Parses the ``config/logging.config.json`` subset. The JSON is parsed with the
hand-rolled :func:`agentlog.json.loads` (stdlib-only) so the project has zero
third-party dependencies.
"""

import os
import tempfile

from agentlog.json import loads
from agentlog.level import Level


class LoggingConfig:
    """Configuration consumed by :class:`agentlog.agentlog.AgentLog`."""

    def __init__(self, service="app", env=None, level="info",
                 redact_enabled=True, redact_paths=None, export_directory=None):
        self.service = service
        self.env = env
        self.level = level
        self.redact_enabled = redact_enabled
        self.redact_paths = list(redact_paths) if redact_paths else []
        self.export_directory = export_directory

    @classmethod
    def from_json(cls, text: str) -> "LoggingConfig":
        """Parse a JSON config string into a :class:`LoggingConfig`.

        Unknown keys are ignored; missing keys fall back to documented defaults.
        """
        d = loads(text)
        if not isinstance(d, dict):
            raise ValueError("config must be a JSON object")

        service = d.get("service", "app")
        if not isinstance(service, str) or service == "":
            service = "app"
        env = d.get("env")
        level = d.get("level", "info")
        # normalize level via from_wire so "warning" (read alias) is accepted
        level = Level.from_wire(level)
        if not Level.is_valid(level):
            level = "info"
        redact_enabled = d.get("redact_enabled", True)
        if not isinstance(redact_enabled, bool):
            redact_enabled = True
        redact_paths = d.get("redact_paths") or []
        export_directory = d.get("export_directory")
        if not export_directory:
            export_directory = os.path.join(tempfile.gettempdir(), "agent-log")

        return cls(
            service=service,
            env=env,
            level=level,
            redact_enabled=redact_enabled,
            redact_paths=redact_paths,
            export_directory=export_directory,
        )

    @classmethod
    def from_file(cls, path: str) -> "LoggingConfig":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_json(fh.read())
