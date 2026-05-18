from __future__ import annotations


class SpoofReversal:
    def signal(self, spoof_score: float, price_move_since_spoof: float) -> float:
        if float(spoof_score) > 50.0 and float(price_move_since_spoof) > 0.0:
            return float(-float(spoof_score) / 100.0)
        return 0.0
