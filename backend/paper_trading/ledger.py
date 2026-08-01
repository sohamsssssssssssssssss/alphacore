"""Persistent run state: equity, positions, rebalance bookkeeping.

Written atomically (tmp + rename) after every mutation so a crash mid-cycle
cannot corrupt state. Everything lives under states/paper_trading/ (gitignored).
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config


class Ledger:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or config.STATE_FILE)
        self.data: dict = {
            "equity": config.INITIAL_CAPITAL,
            "positions": {},      # {symbol: {"leg","qty","entry_price","entry_date","entry_order_id"}}
            "last_rebalance_date": None,
            "rebalance_count": 0,
            "rebalance_done_for_date": None,
            "last_close_capture_date": None,
            "daily_marks": [],     # [{"date", "equity"}]
            "boots": 0,
            "last_error": None,
        }

    def load(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text())
                for k, v in data.items():
                    self.data[k] = v
        except Exception:  # noqa: BLE001
            self.data["last_error"] = "state.json unreadable — starting fresh"

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2))
        tmp.replace(self.path)

    # ── convenience accessors ───────────────────────────────────────────────
    @property
    def equity(self) -> float:
        return float(self.data.get("equity", config.INITIAL_CAPITAL))

    @equity.setter
    def equity(self, value: float) -> None:
        self.data["equity"] = float(value)

    @property
    def positions(self) -> dict:
        return self.data.get("positions", {})

    def set_position(self, symbol: str, pos: dict | None) -> None:
        if pos is None:
            self.data.get("positions", {}).pop(symbol, None)
        else:
            self.data.get("positions", {})[symbol] = pos

    def mark_daily(self, date: str, equity: float) -> None:
        marks = self.data.get("daily_marks", [])
        if marks and marks[-1].get("date") == date:
            marks[-1]["equity"] = equity
        else:
            marks.append({"date": date, "equity": equity})
        self.data["daily_marks"] = marks[-3650:]
