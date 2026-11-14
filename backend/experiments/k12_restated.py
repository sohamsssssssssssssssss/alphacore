"""
In-sample, descriptive restatement of the K=12 NSE basket under Amendment 1.

Same signal (21-session lookback), k = n_ranked // 4, monthly, next-open execution,
point-in-time ADV, CostModel() defaults (brokerage kept, it is a real NSE fee), spread 10 bps,
budget 1,000,000. Basket and equal-weight benchmark (k = all eligible) both use
basket_backtest.simulate_rebalanced. The data were used to choose this basket, so these
figures are descriptive only. Writes research/oos/k12_restated.json (never overwrites).

Run from backend/:  python3.11 -m experiments.k12_restated
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

_BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "experiments"))

from basket_backtest import DEFAULT_BUDGET_INR, monthly_rebalance_dates, simulate_rebalanced  # noqa: E402
from engines.backtest_metrics import compute_sharpe, stationary_bootstrap_sharpe_ci  # noqa: E402
from engines.cost_model import CostModel  # noqa: E402
from oos_basket import _ir  # noqa: E402
from prices import ADV_WINDOW_TRADING_DAYS, point_in_time_adv  # noqa: E402
from universe import UNIVERSE_49  # noqa: E402

NSE_SNAPSHOT = REPO_ROOT / "data_snapshots" / "2026-11"
K12_JSON = REPO_ROOT / "research" / "v2" / "k12_basket.json"
OUT = REPO_ROOT / "research" / "oos" / "k12_restated.json"
AS_OF = date(2026, 8, 13)
RF_ANNUAL = 0.065


def nse_bars(snapshot: Path, symbols: list[str], as_of: date):
    """Closes, opens, volumes from the frozen CSVs, built as prices.fetch_daily_bars builds them. No network."""
    frames = []
    for sym in symbols:
        df = pd.read_csv(snapshot / f"{sym}.csv", index_col=0, parse_dates=True)
        d = pd.DataFrame({"close": df["Close"].dropna(), "volume": df["Volume"].fillna(0.0),
                          "open": df["Open"].dropna()})
        d.columns = [f"{sym}_close", f"{sym}_vol", f"{sym}_open"]
        frames.append(d)
    merged = pd.concat(frames, axis=1).sort_index()
    merged = merged[merged.index <= pd.Timestamp(as_of)]
    closes = merged[[f"{s}_close" for s in symbols]].astype(float)
    closes.columns = symbols
    opens = merged[[f"{s}_open" for s in symbols]].astype(float)
    opens.columns = symbols
    volumes = merged[[f"{s}_vol" for s in symbols]].astype(float)
    volumes.columns = symbols
    return closes, opens, volumes


def _sharpe_block(r: np.ndarray, rf: float) -> dict:
    """Point Sharpe and stationary-bootstrap CI with the existing K12 file's settings (1000, block 10, seed 42)."""
    point = compute_sharpe(r.tolist(), periods_per_year=12, risk_free=rf)
    ci = stationary_bootstrap_sharpe_ci(r.tolist(), n_bootstrap=1000, mean_block_length=10, periods_per_year=12,
                                        seed=42, risk_free=rf)
    return {"sharpe": float(point), "ci_lower": float(ci["ci_lower"]), "ci_upper": float(ci["ci_upper"]),
            "risk_free_annual": rf, "bootstrap": {"n": 1000, "mean_block": 10, "seed": 42, "confidence": 0.95}}


def _exposure(trace: list[dict]) -> dict:
    inv = [r["invested_fraction"] for r in trace]
    return {"first": inv[0], "last": inv[-1], "min": min(inv), "mean": sum(inv) / len(inv), "max": max(inv)}


def run() -> dict:
    symbols = [s for s in UNIVERSE_49 if (NSE_SNAPSHOT / f"{s}.csv").exists()]
    dropped = sorted(set(UNIVERSE_49) - set(symbols))
    closes, opens, volumes = nse_bars(NSE_SNAPSHOT, symbols, AS_OF)
    end = closes.index.max().date()
    sched = monthly_rebalance_dates(closes, end)  # default months_back=72, as the K12 run
    adv = point_in_time_adv(closes, volumes, sched, window=ADV_WINDOW_TRADING_DAYS)
    cm = CostModel()  # defaults unchanged, brokerage included
    kw = dict(cost_model=cm, budget=DEFAULT_BUDGET_INR, spread_bps=10.0, lookback=21)
    bt, bm = [], []
    basket = simulate_rebalanced(closes, opens, adv, sched, k=None, trace=bt, **kw)
    bench = simulate_rebalanced(closes, opens, adv, sched, k=len(closes.columns), trace=bm, **kw)
    if [d for d, _, _ in basket["baskets"]] != [d for d, _, _ in bench["baskets"]]:
        raise RuntimeError("basket and benchmark actionable rebalances differ")

    rb = np.asarray(basket["period_returns"], dtype=float)
    rm = np.asarray(bench["period_returns"], dtype=float)
    active = rb - rm
    ir = _ir(active)
    ci = stationary_bootstrap_sharpe_ci(active.tolist(), n_bootstrap=2000, confidence=0.95, mean_block_length=3,
                                        periods_per_year=12, seed=2026, risk_free=0.0)
    if abs(ci["sharpe"] - ir) > 1e-12:
        raise RuntimeError("active IR does not match bootstrap point")

    ref = json.loads(K12_JSON.read_text())
    return {
        "label": "in-sample, descriptive",
        "amendment": "research/OOS_BASKET_AMENDMENT_1.md",
        "code_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
                                      capture_output=True, text=True).stdout.strip(),
        "data_window": [closes.index.min().date().isoformat(), end.isoformat()],
        "symbols_used": len(symbols),
        "dropped_no_csv": dropped,
        "scheduled_month_ends": len(sched),
        "actionable_first": basket["baskets"][0][0].isoformat(),
        "actionable_last": basket["baskets"][-1][0].isoformat(),
        "n_periods": len(rb),
        "params": {"lookback": 21, "k": "n_ranked // 4 (basket); all eligible (benchmark)", "budget": DEFAULT_BUDGET_INR,
                   "spread_bps": 10.0, "cost_model": "CostModel() defaults", "sizing": "equal weight of equity"},
        "basket": {
            "sharpe_zero_rf": _sharpe_block(rb, 0.0),
            "sharpe_rf_0_065": _sharpe_block(rb, RF_ANNUAL),
            "total_costs": basket["total_costs"],
            "avg_turnover_after_entry": basket["avg_turnover_after_entry"],
            "exposure": _exposure(bt),
            "final_equity": basket["final_equity"],
        },
        "benchmark": {
            "sharpe_zero_rf": _sharpe_block(rm, 0.0),
            "sharpe_rf_0_065": _sharpe_block(rm, RF_ANNUAL),
            "total_costs": bench["total_costs"],
            "avg_turnover_after_entry": bench["avg_turnover_after_entry"],
            "exposure": _exposure(bm),
            "final_equity": bench["final_equity"],
        },
        "active": {
            "ir": ir,
            "ci_lower": float(ci["ci_lower"]),
            "ci_upper": float(ci["ci_upper"]),
            "bootstrap": {"n": 2000, "mean_block": 3, "seed": 2026, "confidence": 0.95},
        },
        "reference_registered_k12_file": {
            "file": "research/v2/k12_basket.json (legacy simulator, not recomputed)",
            "v1_sharpe_rf_0_065": ref["v1_sharpe"], "v2_sharpe_rf_0_065": ref["v2_sharpe"],
            "v2_ci_rf_0_065": ref["v2_ci"], "v2_sharpe_zero_rf": ref["v2_sharpe_zero_rf"],
            "v2_ci_zero_rf": ref["v2_ci_zero_rf"], "nifty50_buy_hold_sharpe_zero_rf": ref["nifty50_buy_hold_sharpe_zero_rf"],
            "equal_weight_buy_hold_sharpe_zero_rf": ref["equal_weight_buy_hold_sharpe_zero_rf"],
        },
    }


def main() -> int:
    res = run()
    with open(OUT, "x", encoding="utf-8") as fh:  # never overwrite
        fh.write(json.dumps(res, indent=2) + "\n")
    print(json.dumps({k: res[k] for k in ("n_periods", "actionable_first", "actionable_last", "dropped_no_csv")}))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
