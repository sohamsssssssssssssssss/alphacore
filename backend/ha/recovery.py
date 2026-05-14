from ha.journal import Journal


class Recovery:
    def __init__(self, journal: Journal):
        self.journal = journal

    async def replay(self) -> dict:
        """
        On startup, read the journal and return a summary of what was
        in-flight before the crash. Does NOT re-execute detections.
        """
        entries = self.journal.read_since()
        return {
            "total_events": len(entries),
            "icebergs": sum(1 for e in entries if e["type"] == "iceberg"),
            "spoofs": sum(1 for e in entries if e["type"] == "spoof"),
            "signals": sum(1 for e in entries if e["type"] == "signal"),
            "circuit_breaks": sum(1 for e in entries if e["type"] == "circuit_break"),
            "last_event_at": entries[-1]["ts"] if entries else None,
            "recovered": True,
        }
