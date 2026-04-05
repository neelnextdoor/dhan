from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from typing import Any


class LogCapture(logging.Handler):
    """Captures log records for the UI log viewer and WebSocket streaming."""

    def __init__(self, maxlen: int = 2000):
        super().__init__()
        self._buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._callbacks: list = []

    def emit(self, record: logging.LogRecord):
        entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            entry["message"] += f"\n{record.exc_info[1]}"

        self._buffer.append(entry)

        for cb in self._callbacks:
            try:
                cb(entry)
            except Exception:
                pass

    def get_logs(self, limit: int = 200, level: str | None = None, module: str | None = None) -> list[dict]:
        logs = list(self._buffer)
        if level:
            logs = [l for l in logs if l["level"] == level.upper()]
        if module:
            logs = [l for l in logs if module.lower() in l["module"].lower()]
        return logs[-limit:]

    def on_log(self, callback):
        self._callbacks.append(callback)

    def clear(self):
        self._buffer.clear()


log_capture = LogCapture()
