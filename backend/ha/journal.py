import asyncio
import json
from datetime import datetime
from pathlib import Path

JOURNAL_PATH = Path("ha/journal.log")


class Journal:
    def __init__(self):
        JOURNAL_PATH.parent.mkdir(exist_ok=True)
        self._lock = asyncio.Lock()
        self._next_seq = self._determine_next_seq()

    def _determine_next_seq(self) -> int:
        entries = self.read_since()
        if not entries:
            return 1
        return entries[-1].get("seq", 0) + 1

    async def write(self, event_type: str, symbol: str, data: dict):
        async with self._lock:
            entry = {
                "seq": self._next_seq,
                "ts": datetime.utcnow().isoformat(),
                "type": event_type,
                "symbol": symbol,
                "data": data,
            }
            self._next_seq += 1
            with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")

    def read_since(self, since_ts: str = None) -> list[dict]:
        """Read journal entries, optionally filtered to after since_ts."""
        entries = []
        if not JOURNAL_PATH.exists():
            return entries
        with open(JOURNAL_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if since_ts is None or entry["ts"] > since_ts:
                        entries.append(entry)
                except Exception:
                    continue
        return entries

    def last_checkpoint(self) -> str | None:
        """Return the timestamp of the last journal entry."""
        entries = self.read_since()
        return entries[-1]["ts"] if entries else None


journal = Journal()
