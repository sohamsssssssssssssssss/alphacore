from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from engines.backtester import BacktestConfig, SYMBOLS, Backtester, run_strategy_comparison

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


class RunRequest(BaseModel):
    symbol: str = "RELIANCE"
    strategy: str = "combined"
    n_snapshots: int = 500
    hold_periods: int = 10
    stop_loss_pct: float = 0.005
    position_size_pct: float = 0.1
    initial_capital: float = 100000.0
    seed: int = 42


class CompareRequest(BaseModel):
    symbol: str = "RELIANCE"
    n_snapshots: int = 500
    hold_periods: int = 10
    stop_loss_pct: float = 0.005
    position_size_pct: float = 0.1
    initial_capital: float = 100000.0
    seed: int = 42


@router.post("/run")
async def run_backtest_post(payload: RunRequest) -> dict:
    cfg = BacktestConfig(**payload.model_dump())
    return Backtester(cfg).run()


@router.get("/run")
async def run_backtest_get(
    symbol: str = "RELIANCE",
    strategy: str = "combined",
    n_snapshots: int = 500,
    hold_periods: int = 10,
    stop_loss_pct: float = 0.005,
    position_size_pct: float = 0.1,
    initial_capital: float = 100000.0,
    seed: int = 42,
) -> dict:
    cfg = BacktestConfig(
        symbol=symbol,
        strategy=strategy,
        n_snapshots=n_snapshots,
        hold_periods=hold_periods,
        stop_loss_pct=stop_loss_pct,
        position_size_pct=position_size_pct,
        initial_capital=initial_capital,
        seed=seed,
    )
    return Backtester(cfg).run()


@router.post("/compare")
async def compare_post(payload: CompareRequest) -> dict:
    return run_strategy_comparison(**payload.model_dump())


@router.get("/compare")
async def compare_get(
    symbol: str = "RELIANCE",
    n_snapshots: int = 500,
    hold_periods: int = 10,
    stop_loss_pct: float = 0.005,
    position_size_pct: float = 0.1,
    initial_capital: float = 100000.0,
    seed: int = 42,
) -> dict:
    return run_strategy_comparison(
        symbol=symbol,
        n_snapshots=n_snapshots,
        hold_periods=hold_periods,
        stop_loss_pct=stop_loss_pct,
        position_size_pct=position_size_pct,
        initial_capital=initial_capital,
        seed=seed,
    )


@router.get("/strategies")
async def get_strategies() -> dict:
    return {
        "strategies": [
            {
                "id": "momentum",
                "name": "Momentum",
                "description": "1/5/15-min weighted price momentum in bps. Threshold +/-2 bps.",
            },
            {
                "id": "mean_reversion",
                "name": "Mean Reversion",
                "description": "20-period z-score. Enters counter-trend at +/-1.5 sigma.",
            },
            {
                "id": "ofi",
                "name": "Order Flow Imbalance",
                "description": "Bid/ask volume ratio [-1,1]. Threshold +/-0.2.",
            },
            {
                "id": "combined",
                "name": "Combined",
                "description": "Equal-weight normalised blend of all three. Threshold +/-0.15.",
            },
        ]
    }


@router.get("/symbols")
async def get_symbols() -> dict:
    return {"symbols": SYMBOLS}


@router.get("/summary")
async def get_summary() -> dict:
    summary: dict[str, dict] = {}
    best_overall = {"symbol": "", "strategy": "", "sharpe": float("-inf")}

    for symbol in SYMBOLS:
        result = run_strategy_comparison(symbol=symbol, n_snapshots=300, seed=42)
        top = result["leaderboard"][0] if result["leaderboard"] else {}
        summary[symbol] = top
        if top and float(top.get("sharpe", float("-inf"))) > best_overall["sharpe"]:
            best_overall = {
                "symbol": symbol,
                "strategy": top.get("strategy", ""),
                "sharpe": float(top.get("sharpe", 0.0)),
            }

    if best_overall["sharpe"] == float("-inf"):
        best_overall = {"symbol": "", "strategy": "", "sharpe": 0.0}

    return {
        "summary": summary,
        "best_overall": best_overall,
    }
