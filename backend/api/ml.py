from __future__ import annotations

from fastapi import APIRouter

from engines.backtester import SYMBOLS
from engines.ml.backtest_ml import backtest_ml_accuracy
from engines.ml.ml_engine import ml_engine

router = APIRouter(prefix="/api/ml", tags=["ml"])


@router.get("/signal/{symbol}")
async def get_signal(symbol: str) -> dict:
    return ml_engine.get_signal(symbol)


@router.get("/signal")
async def get_all_signals() -> list[dict]:
    return [ml_engine.get_signal(s) for s in SYMBOLS]


@router.post("/retrain/{symbol}")
async def retrain(symbol: str) -> dict:
    return ml_engine.retrain(symbol)


@router.get("/metrics/{symbol}")
async def get_metrics(symbol: str) -> dict:
    m = ml_engine.get_metrics(symbol)
    if "feature_importance" in m:
        fi = sorted(m["feature_importance"].items(), key=lambda kv: kv[1], reverse=True)
        m["feature_importance_ranked"] = fi
    return m


@router.get("/metrics")
async def get_all_metrics() -> list[dict]:
    return [await get_metrics(s) for s in SYMBOLS]


@router.get("/leaderboard")
async def leaderboard() -> list[dict]:
    rows = []
    for s in SYMBOLS:
        m = ml_engine.get_metrics(s)
        sig = ml_engine.get_signal(s)
        rows.append(
            {
                "symbol": s,
                "accuracy": float(m.get("accuracy", 0.0)),
                "directional_accuracy": float(m.get("directional_accuracy", 0.0)),
                "f1": float(m.get("f1", 0.0)),
                "current_signal": sig.get("direction", "DOWN"),
                "confidence": float(sig.get("confidence", 0.0)),
            }
        )
    return sorted(rows, key=lambda x: x["accuracy"], reverse=True)


@router.get("/backtest/{symbol}")
async def backtest(symbol: str) -> dict:
    return backtest_ml_accuracy(symbol=symbol, n_snapshots=2000, lookahead=30, n_folds=5)
