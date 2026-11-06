"""AgentLog facade: thin, idiomatic entry point.

``AgentLog`` is usable both as a module-level singleton (``AgentLog.bootstrap()``,
``AgentLog.info(...)``) and as an explicit instance (``AgentLog().child(...)``).
All class-level calls delegate to a process-wide singleton so state is shared.
"""

from agentlog.config import LoggingConfig
from agentlog.coretypes import get_session_id
from agentlog.level import Level
from agentlog.logger import Logger
from agentlog.redactor import Redactor
from agentlog.sink import FileSink, MemorySink

# Process-wide singleton used by the classmethod/function facade.
_AGENTLOG = None


def _singleton() -> "AgentLog":
    global _AGENTLOG
    if _AGENTLOG is None:
        _AGENTLOG = AgentLog()
    return _AGENTLOG


class AgentLog:
    """Singleton-backed facade over a :class:`Logger`."""

    def __init__(self):
        self._logger = None
        self._config = None
        self._session_id = get_session_id()

    # -- bootstrap --------------------------------------------------------- #
    def bootstrap(self, config: LoggingConfig = None, config_json: str = None,
                  sink=None) -> "AgentLog":
        if config is None and config_json is not None:
            config = LoggingConfig.from_json(config_json)
        if config is None:
            config = LoggingConfig()
        self._config = config

        redactor = Redactor(enabled=config.redact_enabled,
                            custom_paths=config.redact_paths)
        if sink is None:
            sink = FileSink(config.export_directory)
        self._logger = Logger(
            service=config.service,
            min_level=Level.from_name(config.level),
            context={},
            sink=sink,
            redactor=redactor,
            session_id=self._session_id,
            redact_enabled=config.redact_enabled,
            env=config.env,
        )
        return self

    @property
    def logger(self) -> Logger:
        if self._logger is None:
            self.bootstrap()
        return self._logger

    # -- delegation (instance) --------------------------------------------- #
    def info(self, message, category="app", trace_id=None, payload=None):
        self.logger.info(message, category, trace_id, payload)

    def warn(self, message, category="app", trace_id=None, payload=None):
        self.logger.warn(message, category, trace_id, payload)

    def warning(self, message, category="app", trace_id=None, payload=None):
        self.logger.warn(message, category, trace_id, payload)

    def error(self, message, category="app", trace_id=None, payload=None):
        self.logger.error(message, category, trace_id, payload)

    def debug(self, message, category="app", trace_id=None, payload=None):
        self.logger.debug(message, category, trace_id, payload)

    def trace(self, message, category="app", trace_id=None, payload=None):
        self.logger.trace(message, category, trace_id, payload)

    def critical(self, message, category="app", trace_id=None, payload=None):
        self.logger.critical(message, category, trace_id, payload)

    def record_auto(self, event_type, message, category="auto", trace_id=None, payload=None):
        self.logger.record_auto(event_type, message, category, trace_id, payload)

    def child(self, context: dict) -> Logger:
        return self.logger.child(context)

    def set_level(self, level: str) -> None:
        self.logger.set_level(level)

    def redact(self, paths) -> None:
        self.logger.redact(paths)

    def export_path(self):
        return self.logger.export_path()

    def config(self):
        return self._config

    # -- classmethod / singleton facade ----------------------------------- #
    @classmethod
    def bootstrap_singleton(cls, config=None, config_json=None, sink=None):
        return _singleton().bootstrap(config, config_json, sink)

    @classmethod
    def instance(cls) -> "AgentLog":
        return _singleton()

    @classmethod
    def info_s(cls, message, category="app", trace_id=None, payload=None):
        _singleton().info(message, category, trace_id, payload)

    @classmethod
    def warn_s(cls, message, category="app", trace_id=None, payload=None):
        _singleton().warn(message, category, trace_id, payload)

    @classmethod
    def warning_s(cls, message, category="app", trace_id=None, payload=None):
        _singleton().warning(message, category, trace_id, payload)

    @classmethod
    def error_s(cls, message, category="app", trace_id=None, payload=None):
        _singleton().error(message, category, trace_id, payload)

    @classmethod
    def debug_s(cls, message, category="app", trace_id=None, payload=None):
        _singleton().debug(message, category, trace_id, payload)

    @classmethod
    def trace_s(cls, message, category="app", trace_id=None, payload=None):
        _singleton().trace(message, category, trace_id, payload)

    @classmethod
    def critical_s(cls, message, category="app", trace_id=None, payload=None):
        _singleton().critical(message, category, trace_id, payload)

    @classmethod
    def record_auto_s(cls, event_type, message, category="auto", trace_id=None, payload=None):
        _singleton().record_auto(event_type, message, category, trace_id, payload)

    @classmethod
    def child_s(cls, context: dict) -> Logger:
        return _singleton().child(context)

    @classmethod
    def set_level_s(cls, level: str) -> None:
        _singleton().set_level(level)

    @classmethod
    def redact_s(cls, paths) -> None:
        _singleton().redact(paths)

    @classmethod
    def export_path_s(cls):
        return _singleton().export_path()


# --------------------------------------------------------------------------- #
# Module-level convenience functions (also satisfy the facade contract)
# --------------------------------------------------------------------------- #
def bootstrap(config: LoggingConfig = None, config_json: str = None, sink=None):
    return _singleton().bootstrap(config, config_json, sink)


def instance() -> AgentLog:
    return _singleton()


def info(message, category="app", trace_id=None, payload=None):
    _singleton().info(message, category, trace_id, payload)


def warn(message, category="app", trace_id=None, payload=None):
    _singleton().warn(message, category, trace_id, payload)


def warning(message, category="app", trace_id=None, payload=None):
    _singleton().warning(message, category, trace_id, payload)


def error(message, category="app", trace_id=None, payload=None):
    _singleton().error(message, category, trace_id, payload)


def debug(message, category="app", trace_id=None, payload=None):
    _singleton().debug(message, category, trace_id, payload)


def trace(message, category="app", trace_id=None, payload=None):
    _singleton().trace(message, category, trace_id, payload)


def critical(message, category="app", trace_id=None, payload=None):
    _singleton().critical(message, category, trace_id, payload)


def record_auto(event_type, message, category="auto", trace_id=None, payload=None):
    _singleton().record_auto(event_type, message, category, trace_id, payload)


def child(context: dict) -> Logger:
    return _singleton().child(context)


def set_level(level: str) -> None:
    _singleton().set_level(level)


def redact(paths) -> None:
    _singleton().redact(paths)


def export_path():
    return _singleton().export_path()
