"""
Out-of-sample Arm A runner: long-only top-quartile basket vs equal-weight
benchmark on a frozen S&P 100 snapshot. Specification: research/OOS_BASKET_PROTOCOL.md.

Reuses rank_table / top_quartile / simulate. The only change to simulate is
the adv_by_date path, and it is opt-in. Bootstrap is the existing
engines.backtest_metrics.stationary_bootstrap_sharpe_ci, whose point estimate
is mean/std*sqrt(ppy) with no risk-free term. That is exactly the protocol's
IR, so it is used as the statistic with no new resampler.

Eligibility: a name is rankable at a rebalance only if it has a full
63-session point-in-time ADV window there (no partial windows, no substitute
impact). Basket and benchmark use the same rule.

Run from backend/ (python3.11), once:
    python3.11 -m experiments.oos_basket
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

_BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))  # engines.*
sys.path.insert(0, str(_BACKEND / "experiments"))  # basket_backtest (also wires sandbox/)

from basket_backtest import (ASSUMED_SPREAD_BPS, DEFAULT_BUDGET_INR, monthly_rebalance_dates,  # noqa: E402
                             simulate, simulate_rebalanced)
from engines.backtest_metrics import stationary_bootstrap_sharpe_ci  # noqa: E402
from engines.cost_model import CostModel  # noqa: E402
from prices import ADV_WINDOW_TRADING_DAYS, point_in_time_adv  # noqa: E402
from rs_signal import LOOKBACK_TRADING_DAYS  # noqa: E402

PROTOCOL_PATH = "research/OOS_BASKET_PROTOCOL.md"
LOOKBACK = LOOKBACK_TRADING_DAYS  # 21
BUDGET = DEFAULT_BUDGET_INR  # 1,000,000
SPREAD_BPS = ASSUMED_SPREAD_BPS  # 10
PERIODS_PER_YEAR = 12
N_BOOTSTRAP = 2000
MEAN_BLOCK = 3
SEED = 2026
CONFIDENCE = 0.95


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def yahoo_symbol(ticker: str) -> str:
    return ticker.replace(".", "-")


def read_universe(path: Path) -> tuple[list[str], list[str]]:
    """Return (header comment lines, tickers). Blank lines are skipped."""
    lines = path.read_text(encoding="utf-8").splitlines()
    header = [ln for ln in lines if ln.startswith("#")]
    tickers = [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]
    return header, tickers


def load_snapshot(snapshot_dir: Path, tickers: list[str]):
    """
    Load frozen daily bars. Every CSV is hash-checked against MANIFEST.json.
    Tickers listed as unavailable in the manifest are not substituted.
    Returns (closes, opens, volumes, unavailable) with columns = Yahoo symbols.
    """
    manifest = json.loads((snapshot_dir / "MANIFEST.json").read_text())
    unavailable = manifest["unavailable"]
    closes, opens, volumes = {}, {}, {}
    for ticker in tickers:
        if ticker in unavailable:
            continue
        sym = yahoo_symbol(ticker)
        name = f"{sym}.csv"
        path = snapshot_dir / name
        entry = manifest["files"].get(name)
        if entry is None or not path.is_file() or sha256(path) != entry["sha256"]:
            raise RuntimeError(f"frozen snapshot missing or hash mismatch: {path}")
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df["Close"].dropna().empty:
            raise RuntimeError(f"{name} has no close prices; list it as unavailable in the manifest")
        closes[sym] = df["Close"].astype(float)
        opens[sym] = df["Open"].astype(float)
        volumes[sym] = df["Volume"].astype(float)
    closes_df = pd.DataFrame(closes).sort_index()
    opens_df = pd.DataFrame(opens).reindex(closes_df.index)
    volumes_df = pd.DataFrame(volumes).reindex(closes_df.index)
    return closes_df, opens_df, volumes_df, unavailable


def _ir(active: np.ndarray) -> float:
    std = float(np.std(active))
    if std == 0.0:
        return 0.0
    return float(np.mean(active) / std * np.sqrt(PERIODS_PER_YEAR))


def run_arm(closes: pd.DataFrame, opens: pd.DataFrame, volumes: pd.DataFrame, *, basket_k: int | None = None) -> dict:
    """
    Run the locked strategy and the all-member benchmark over every month-end.
    basket_k is for tests only (the production call leaves it None = n//4).
    """
    first, end = closes.index.min().date(), closes.index.max().date()
    months_back = (end.year - first.year) * 12 + (end.month - first.month) + 1
    sched = monthly_rebalance_dates(closes, end, months_back=months_back)
    assert (sched[0].year, sched[0].month) == (first.year, first.month), f"first rebalance {sched[0]}"
    assert (sched[-1].year, sched[-1].month) == (end.year, end.month), f"last rebalance {sched[-1]}"
    assert len(sched) == months_back, f"{len(sched)} month-ends for {months_back} months"

    adv_by_date = point_in_time_adv(closes, volumes, sched, window=ADV_WINDOW_TRADING_DAYS)
    kw = dict(budget=BUDGET, spread_bps=SPREAD_BPS, lookback=LOOKBACK, adv_by_date=adv_by_date)
    basket = simulate(closes, {}, opens, sched, k=basket_k, **kw)
    bench = simulate(closes, {}, opens, sched, k=len(closes.columns), **kw)

    b_dates = [d for d, _, _ in basket["baskets"]]
    m_dates = [d for d, _, _ in bench["baskets"]]
    if b_dates != m_dates:
        raise RuntimeError("basket and benchmark actionable rebalances differ")
    # period_returns[j] is the return ending at actionable rebalance j+1.
    period_dates = b_dates[1:]
    assert len(period_dates) == len(basket["period_returns"]) == len(bench["period_returns"])

    b_ret = np.asarray(basket["period_returns"], dtype=float)
    m_ret = np.asarray(bench["period_returns"], dtype=float)
    active = b_ret - m_ret
    ir = _ir(active)
    ci = stationary_bootstrap_sharpe_ci(active.tolist(), n_bootstrap=N_BOOTSTRAP, confidence=CONFIDENCE,
                                        mean_block_length=MEAN_BLOCK, periods_per_year=PERIODS_PER_YEAR,
                                        seed=SEED, risk_free=0.0)
    if abs(ci["sharpe"] - ir) > 1e-12:
        raise RuntimeError(f"bootstrap point {ci['sharpe']} != IR {ir}")
    lo, hi = ci["ci_lower"], ci["ci_upper"]
    outcome = "Pass" if lo > 0 else ("Fail" if hi < 0 else "Inconclusive")

    monthly = [{"rebalance_date": d.isoformat(), "basket_net": float(b), "benchmark_net": float(m),
                "active": float(b - m)}
               for d, b, m in zip(period_dates, b_ret, m_ret)]
    return {
        "params": {
            "lookback_sessions": LOOKBACK,
            "k_rule": "n_ranked // 4 (basket); all rankable names (benchmark)",
            "schedule": "last trading session of each month; trade at next session open",
            "adv": f"point-in-time mean(close*volume) over {ADV_WINDOW_TRADING_DAYS} sessions ending on rebalance day",
            "eligibility": "rankable only with a full point-in-time ADV window",
            "budget": BUDGET,
            "spread_bps": SPREAD_BPS,
            "cost_model": "engines.cost_model.CostModel() defaults",
            "bootstrap": {"type": "stationary", "n_bootstrap": N_BOOTSTRAP, "mean_block": MEAN_BLOCK,
                          "seed": SEED, "confidence": CONFIDENCE, "periods_per_year": PERIODS_PER_YEAR,
                          "risk_free": 0.0},
        },
        "n_months": len(monthly),
        "scheduled_month_ends": len(sched),
        "scheduled_first": sched[0].isoformat(),
        "scheduled_last": sched[-1].isoformat(),
        "actionable_first": b_dates[0].isoformat(),
        "actionable_last": b_dates[-1].isoformat(),
        "monthly": monthly,
        "ir": ir,
        "ci_lower": float(lo),
        "ci_upper": float(hi),
        "outcome": outcome,
        "basket_ir_point": float(basket_ir(b_ret)),
        "benchmark_ir_point": float(basket_ir(m_ret)),
        "costs": {
            "budget": BUDGET,
            "basket_total_costs": float(basket["total_costs"]),
            "benchmark_total_costs": float(bench["total_costs"]),
        },
        "turnover": {
            "basket_avg_legs_per_rebalance": basket["avg_legs_per_rebalance"],
            "basket_avg_one_sided_turnover": basket["avg_turnover_fraction"],
            "benchmark_avg_legs_per_rebalance": bench["avg_legs_per_rebalance"],
            "benchmark_avg_one_sided_turnover": bench["avg_turnover_fraction"],
        },
        "basket_sizes": [[d.isoformat(), n] for d, _, n in basket["baskets"]],
        "eligible_counts": {d.isoformat(): len(v) for d, v in adv_by_date.items()},
        "skipped_rebalances": {"basket": basket["skipped_rebalances"], "benchmark": bench["skipped_rebalances"]},
    }


AMENDMENT_PATH = "research/OOS_BASKET_AMENDMENT_1.md"
CORRECTED_BROKERAGE = 0.0  # Amendment 1: flat per-trade brokerage set to 0 for the US run


def amendment_outcome(lo: float, hi: float) -> str:
    """Amendment 1 wording table. The corrected analysis cannot produce a pass."""
    if hi < 0:
        return "not supported, also after correction"
    if lo > 0:
        return "candidate only"
    return "no evidence of an edge"


def _exposure(trace: list[dict]) -> dict:
    inv = [r["invested_fraction"] for r in trace]
    return {"first": inv[0], "last": inv[-1], "min": min(inv), "mean": sum(inv) / len(inv), "max": max(inv),
            "n_rebalances": len(inv)}


def run_corrected_arm(closes: pd.DataFrame, opens: pd.DataFrame, volumes: pd.DataFrame, *,
                      basket_k: int | None = None) -> dict:
    """
    Amendment 1 analysis: same schedule, eligibility, window and metric as run_arm; the
    corrected equal-weight simulator for basket and benchmark; brokerage 0 on the US run.
    basket_k is for tests only (production leaves it None = n//4).
    """
    first, end = closes.index.min().date(), closes.index.max().date()
    months_back = (end.year - first.year) * 12 + (end.month - first.month) + 1
    sched = monthly_rebalance_dates(closes, end, months_back=months_back)
    assert (sched[0].year, sched[0].month) == (first.year, first.month), f"first rebalance {sched[0]}"
    assert (sched[-1].year, sched[-1].month) == (end.year, end.month), f"last rebalance {sched[-1]}"
    assert len(sched) == months_back, f"{len(sched)} month-ends for {months_back} months"

    adv_by_date = point_in_time_adv(closes, volumes, sched, window=ADV_WINDOW_TRADING_DAYS)
    kw = dict(cost_model=CostModel(brokerage_per_trade=CORRECTED_BROKERAGE), budget=BUDGET,
              spread_bps=SPREAD_BPS, lookback=LOOKBACK)
    bt_trace, bm_trace = [], []
    basket = simulate_rebalanced(closes, opens, adv_by_date, sched, k=basket_k, trace=bt_trace, **kw)
    bench = simulate_rebalanced(closes, opens, adv_by_date, sched, k=len(closes.columns), trace=bm_trace, **kw)

    b_dates = [d for d, _, _ in basket["baskets"]]
    if b_dates != [d for d, _, _ in bench["baskets"]]:
        raise RuntimeError("basket and benchmark actionable rebalances differ")
    period_dates = b_dates[1:]
    assert len(period_dates) == len(basket["period_returns"]) == len(bench["period_returns"])

    b_ret = np.asarray(basket["period_returns"], dtype=float)
    m_ret = np.asarray(bench["period_returns"], dtype=float)
    active = b_ret - m_ret
    ir = _ir(active)
    ci = stationary_bootstrap_sharpe_ci(active.tolist(), n_bootstrap=N_BOOTSTRAP, confidence=CONFIDENCE,
                                        mean_block_length=MEAN_BLOCK, periods_per_year=PERIODS_PER_YEAR,
                                        seed=SEED, risk_free=0.0)
    if abs(ci["sharpe"] - ir) > 1e-12:
        raise RuntimeError(f"bootstrap point {ci['sharpe']} != IR {ir}")
    lo, hi = ci["ci_lower"], ci["ci_upper"]
    monthly = [{"rebalance_date": d.isoformat(), "basket_net": float(b), "benchmark_net": float(m),
                "active": float(b - m)} for d, b, m in zip(period_dates, b_ret, m_ret)]
    return {
        "params": {
            "lookback_sessions": LOOKBACK,
            "k_rule": "basket n_ranked // 4; benchmark all eligible names",
            "sizing": "equal weight of current equity at each rebalance, fractional shares, cash 0-1% after fills",
            "schedule": "last trading session of each month; trade at next session open",
            "adv": f"point-in-time mean(close*volume) over {ADV_WINDOW_TRADING_DAYS} sessions ending on rebalance day",
            "eligibility": "rankable only with a full point-in-time ADV window",
            "budget": BUDGET,
            "spread_bps": SPREAD_BPS,
            "cost_model": f"engines.cost_model.CostModel(brokerage_per_trade={CORRECTED_BROKERAGE}), other defaults",
            "bootstrap": {"type": "stationary", "n_bootstrap": N_BOOTSTRAP, "mean_block": MEAN_BLOCK,
                          "seed": SEED, "confidence": CONFIDENCE, "periods_per_year": PERIODS_PER_YEAR,
                          "risk_free": 0.0},
        },
        "n_months": len(monthly),
        "scheduled_month_ends": len(sched),
        "scheduled_first": sched[0].isoformat(),
        "scheduled_last": sched[-1].isoformat(),
        "actionable_first": b_dates[0].isoformat(),
        "actionable_last": b_dates[-1].isoformat(),
        "monthly": monthly,
        "ir": ir,
        "ci_lower": float(lo),
        "ci_upper": float(hi),
        "outcome": amendment_outcome(lo, hi),
        "basket_ir_point": float(basket_ir(b_ret)),
        "benchmark_ir_point": float(basket_ir(m_ret)),
        "costs": {
            "basket_total_costs": float(basket["total_costs"]),
            "benchmark_total_costs": float(bench["total_costs"]),
        },
        "turnover": {
            "basket_avg_turnover_after_entry": basket["avg_turnover_after_entry"],
            "benchmark_avg_turnover_after_entry": bench["avg_turnover_after_entry"],
        },
        "exposure": {
            "basket": _exposure(bt_trace),
            "benchmark": _exposure(bm_trace),
            "basket_carried": len(basket["carried"]), "benchmark_carried": len(bench["carried"]),
            "basket_skipped_buys": len(basket["skipped_buys"]), "benchmark_skipped_buys": len(bench["skipped_buys"]),
            "basket_rebalances": [{k: r[k] for k in ("rebalance", "equity", "cash", "holdings_value",
                                                     "invested_fraction", "n_positions", "turnover")}
                                  for r in bt_trace],
            "benchmark_rebalances": [{k: r[k] for k in ("rebalance", "equity", "cash", "holdings_value",
                                                        "invested_fraction", "n_positions", "turnover")}
                                     for r in bm_trace],
        },
        "basket_sizes": [[d.isoformat(), n] for d, _, n in basket["baskets"]],
        "eligible_counts": {d.isoformat(): len(v) for d, v in adv_by_date.items()},
        "skipped_rebalances": {"basket": basket["skipped_rebalances"], "benchmark": bench["skipped_rebalances"]},
    }


def basket_ir(period: np.ndarray) -> float:
    return _ir(np.asarray(period, dtype=float))


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True).stdout.strip()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="OOS Arm A: top-quartile basket vs benchmark (run once)")
    p.add_argument("--snapshot", type=Path, default=REPO_ROOT / "data_snapshots" / "us-2026-11")
    p.add_argument("--universe", type=Path, default=None, help="default: <snapshot>/universe.txt")
    p.add_argument("--mode", choices=["registered", "corrected"], default="registered",
                   help="registered: protocol as written (arm_a.json); corrected: Amendment 1 (arm_a_corrected.json)")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)
    corrected = args.mode == "corrected"
    out_path = args.out or (REPO_ROOT / "research" / "oos" / ("arm_a_corrected.json" if corrected else "arm_a.json"))

    if out_path.exists():
        print(f"[REFUSED] {out_path} exists; Arm A runs once", file=sys.stderr)
        return 2

    universe_path = args.universe or args.snapshot / "universe.txt"
    header, tickers = read_universe(universe_path)
    closes, opens, volumes, unavailable = load_snapshot(args.snapshot, tickers)
    res = run_corrected_arm(closes, opens, volumes) if corrected else run_arm(closes, opens, volumes)

    out = {
        "arm": "A-corrected" if corrected else "A",
        "protocol": PROTOCOL_PATH,
        "protocol_commit": _git("log", "-1", "--format=%H", "--", PROTOCOL_PATH),
        **({"amendment": AMENDMENT_PATH, "amendment_commit": _git("log", "-1", "--format=%H", "--", AMENDMENT_PATH)}
           if corrected else {}),
        "code_commit": _git("rev-parse", "HEAD"),
        "code_dirty_tracked_files": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "universe_file": str(universe_path.relative_to(REPO_ROOT)),
        "universe_sha256": sha256(universe_path),
        "universe_header": header,
        "manifest_sha256": sha256(args.snapshot / "MANIFEST.json"),
        "data_window": [closes.index.min().date().isoformat(), closes.index.max().date().isoformat()],
        "tickers_requested": len(tickers),
        "symbols_loaded": len(closes.columns),
        "unavailable": unavailable,
        **res,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "x", encoding="utf-8") as fh:  # mode "x": never overwrite a run
        fh.write(json.dumps(out, indent=2) + "\n")
    print(f"[{out['arm']}] months={out['n_months']} IR={out['ir']:.4f} "
          f"CI95=[{out['ci_lower']:.4f}, {out['ci_upper']:.4f}] outcome={out['outcome']}")
    print(f"[{out['arm']}] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
