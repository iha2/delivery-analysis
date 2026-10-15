from __future__ import annotations

import os
import sys
from datetime import datetime


class RunLog:
    """Write timestamped run output to a log file and stderr."""

    def __init__(self, path: str) -> None:
        self.path = os.path.expanduser(path)
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._handle = open(self.path, "w", encoding="utf-8")
        self.info(f"Run log started: {self.path}")

    def close(self) -> None:
        if not self._handle.closed:
            self.info("Run log closed")
            self._handle.close()

    def __enter__(self) -> RunLog:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is not None:
            self.error(f"Run failed: {exc}")
        self.close()

    def _emit(self, level: str, message: str) -> None:
        line = f"{datetime.now().isoformat(timespec='seconds')} [{level}] {message}"
        self._handle.write(line + "\n")
        self._handle.flush()
        print(line, file=sys.stderr)

    def info(self, message: str) -> None:
        self._emit("INFO", message)

    def warn(self, message: str) -> None:
        self._emit("WARN", message)

    def error(self, message: str) -> None:
        self._emit("ERROR", message)
