from __future__ import annotations


class IcebergPressure:
    def signal(self, iceberg_confidence: float, iceberg_side: str, hidden_vol_estimate: float) -> float:
        side = (iceberg_side or "").upper()
        mag = float(iceberg_confidence) * float(hidden_vol_estimate)
        if side == "BID":
            return float(mag)
        if side == "ASK":
            return float(-mag)
        return 0.0
