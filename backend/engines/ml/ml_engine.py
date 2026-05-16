from __future__ import annotations

from collections import defaultdict

from engines.backtester import Snapshot, generate_snapshots
from engines.ml.trainer import predict, train_model


class MLEngine:
    def __init__(self):
        self._models: dict[str, bytes] = {}
        self._metrics: dict[str, dict] = {}
        self._history: dict[str, list[Snapshot]] = defaultdict(list)
        self._seed: dict[str, int] = defaultdict(lambda: 42)

    def is_trained(self, symbol: str) -> bool:
        return symbol.upper() in self._models

    def _ensure_trained(self, symbol: str):
        sym = symbol.upper()
        if sym in self._models:
            return
        snaps = generate_snapshots(sym, 1000, seed=self._seed[sym])
        self._history[sym] = snaps
        res = train_model(snaps, lookahead=30)
        if "error" in res:
            self._metrics[sym] = res
            return
        self._models[sym] = res.pop("model_bytes")
        self._metrics[sym] = res

    def get_signal(self, symbol: str) -> dict:
        sym = symbol.upper()
        self._ensure_trained(sym)
        if sym not in self._models:
            return {"symbol": sym, "error": "insufficient data"}

        # Append one synthetic new snapshot for drift.
        seed = self._seed[sym] + 1
        self._seed[sym] = seed
        new_snap = generate_snapshots(sym, 1, seed=seed)[0]
        self._history[sym].append(new_snap)

        pred = predict(self._models[sym], self._history[sym], len(self._history[sym]) - 1)
        return {
            "symbol": sym,
            **pred,
            "training": {
                "accuracy": float(self._metrics[sym].get("accuracy", 0.0)),
                "f1": float(self._metrics[sym].get("f1", 0.0)),
            },
        }

    def retrain(self, symbol: str) -> dict:
        sym = symbol.upper()
        snaps = generate_snapshots(sym, 1000, seed=self._seed[sym] + 100)
        self._history[sym] = snaps
        res = train_model(snaps, lookahead=30)
        if "error" in res:
            self._metrics[sym] = res
            return {"symbol": sym, **res}
        self._models[sym] = res.pop("model_bytes")
        self._metrics[sym] = res
        return {"symbol": sym, **res}

    def get_metrics(self, symbol: str) -> dict:
        sym = symbol.upper()
        self._ensure_trained(sym)
        return {"symbol": sym, **self._metrics.get(sym, {"error": "insufficient data"})}


ml_engine = MLEngine()
