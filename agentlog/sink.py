"""Sinks: destinations for serialized log lines.

* :class:`FileSink`   -> appends JSONL to ``<export_directory>/agent-log.jsonl``
* :class:`MemorySink` -> keeps lines in an in-memory list (for tests)
"""

import os
import tempfile


class Sink:
    """Base sink: accepts a single already-serialized JSONL string."""

    def write(self, line: str) -> None:
        raise NotImplementedError

    def lines(self):
        raise NotImplementedError

    def export_path(self):
        return None


class FileSink(Sink):
    def __init__(self, export_directory=None, filename="agent-log.jsonl"):
        if export_directory is None:
            export_directory = os.path.join(tempfile.gettempdir(), "agent-log")
        self.export_directory = export_directory
        self.filename = filename
        os.makedirs(self.export_directory, exist_ok=True)
        self._path = os.path.join(self.export_directory, self.filename)

    def write(self, line: str) -> None:
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(line)
            if not line.endswith("\n"):
                fh.write("\n")

    def export_path(self):
        return self._path


class MemorySink(Sink):
    def __init__(self):
        self._lines = []

    def write(self, line: str) -> None:
        self._lines.append(line)

    def lines(self):
        return list(self._lines)

    def clear(self):
        self._lines.clear()
