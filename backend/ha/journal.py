import asyncio
import json
from datetime import datetime
from pathlib import Path

JOURNAL_PATH = Path("ha/journal.log")


class Journal:
    def __init__(self):
        JOURNAL_PATH.parent.mkdir(exist_ok=True)
        self._lock = asyncio.Lock()

    async def write(self, event_type: str, symbol: str, data: dict):
        entry = {
            "ts": datetime.utcnow().isoformat(),
            "type": event_type,
            "symbol": symbol,
            "data": data,
        }
        async with self._lock:
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
