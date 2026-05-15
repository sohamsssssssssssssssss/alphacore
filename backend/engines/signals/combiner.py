from __future__ import annotations

from collections import defaultdict, deque
import numpy as np


class SignalCombiner:
    def __init__(self):
        self._perf: dict[str, dict[str, deque[float]]] = defaultdict(
            lambda: {
                "momentum": deque(maxlen=50),
                "mean_reversion": deque(maxlen=50),
                "order_flow": deque(maxlen=50),
            }
        )

    def update_performance(self, signal_name: str, symbol: str, pnl_bps: float):
        if signal_name not in {"momentum", "mean_reversion", "order_flow"}:
            return
        self._perf[symbol.upper()][signal_name].append(float(pnl_bps))

    def _sharpe(self, xs: deque[float]) -> float:
        if len(xs) < 2:
            return 0.0
        arr = np.array(xs, dtype=float)
        std = float(arr.std())
        if std == 0:
            return 0.0
        return float(arr.mean() / std)

    def get_weights(self, symbol: str) -> dict:
        sym = symbol.upper()
        perf = self._perf[sym]
        obs = min(len(perf["momentum"]), len(perf["mean_reversion"]), len(perf["order_flow"]))
        if obs < 10:
            return {"momentum": 1 / 3, "mean_reversion": 1 / 3, "order_flow": 1 / 3}

        sharpes = {k: self._sharpe(v) for k, v in perf.items()}
        positive = {k: s for k, s in sharpes.items() if s > 0}
        if not positive:
            return {"momentum": 1 / 3, "mean_reversion": 1 / 3, "order_flow": 1 / 3}
        total = sum(positive.values())
        return {k: (positive.get(k, 0.0) / total) for k in ["momentum", "mean_reversion", "order_flow"]}

    def combine(self, symbol: str, momentum_out: dict | None, meanrev_out: dict | None, orderflow_out: dict | None) -> dict:
        outs = {
            "momentum": momentum_out,
            "mean_reversion": meanrev_out,
            "order_flow": orderflow_out,
        }
        base_weights = self.get_weights(symbol)
        active = [k for k, v in outs.items() if v is not None]
        if not active:
            return {
                "combined_signal": 0.0,
                "combined_direction": "FLAT",
                "confidence": 0.0,
                "alpha_score": 50.0,
                "weights_used": base_weights,
            }

        wsum = sum(base_weights[k] for k in active)
        weights = {k: (base_weights[k] / wsum if k in active else 0.0) for k in base_weights}

        combined_signal = 0.0
        vote_scores = {"LONG": 0.0, "SHORT": 0.0, "FLAT": 0.0}
        directions = []
        for name, out in outs.items():
            if out is None:
                continue
            sig = float(out.get("signal", 0.0))
            combined_signal += weights[name] * sig
            direction = out.get("direction", "FLAT")
            strength = float(out.get("strength", 0.0))
            vote_scores[direction] = vote_scores.get(direction, 0.0) + weights[name] * strength
            directions.append(direction)

        combined_direction = max(vote_scores.items(), key=lambda kv: kv[1])[0]
        total_vote = sum(vote_scores.values())
        if total_vote <= 0:
            confidence = 0.0
        else:
            long_short_balance = abs(vote_scores.get("LONG", 0.0) - vote_scores.get("SHORT", 0.0))
            confidence = max(0.0, min(1.0, long_short_balance / total_vote))

        alpha_score = max(0.0, min(100.0, 50.0 + combined_signal))
        return {
            "combined_signal": float(combined_signal),
            "combined_direction": combined_direction,
            "confidence": float(confidence),
            "alpha_score": float(alpha_score),
            "weights_used": weights,
        }
