"""Append-only JSONL event log.

Every event is one JSON line: {"ts": ISO8601, "type": str, "data": {...}}.
Append-only by construction (each write opens in 'a' mode); a single
write-through file so the run can be analyzed at any checkpoint without the
scheduler running.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import config

_EVENTS = (
    "boot", "cycle", "auth_expired", "auth_reloaded", "token_warning",
    "market_data_error", "close_capture", "daily_mtm", "rebalance_start",
    "order_submitted", "order_poll", "order_terminal", "trade",
    "fill_sanity_fail", "close_unresolved", "instrument_fallback",
    "rebalance_skipped", "rebalance_complete", "error", "warning",
    "kill_detected", "shutdown",
)


class EventLog:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or config.LOG_FILE)

    def _emit(self, type_: str, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": type_,
            "data": data,
        })
        with self.path.open("a") as f:
            f.write(line + "\n")

    def __getattr__(self, name: str):
        if name in _EVENTS:
            def _emit(data: dict) -> None:
                self._emit(name, data)
            return _emit
        raise AttributeError(name)

    def log(self, type_: str, data: dict) -> None:
        if type_ in _EVENTS:
            self._emit(type_, data)
        else:
            self._emit("error", {"msg": f"unknown event type {type_}", "data": data})
