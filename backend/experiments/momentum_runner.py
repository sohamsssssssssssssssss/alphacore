"""
12-1 momentum runner, per research/MOMENTUM_12_1_PROTOCOL.md. Run once.

Basket: top n_eligible // 5 by 12-1 signal. Benchmark: all eligible names. Both through
basket_backtest.simulate_rebalanced with CostModel(brokerage_per_trade=0) and other defaults,
spread 30 bps, budget 10,000,000, month-end rebalances, next-session open.

Start at the first month-end with >= 50 eligible names. From then on, no grace period:
invested fraction must stay in [0.99, 1.00] and eligible count >= 50, before return statistics.

Run from backend/:  python3.11 -m experiments.momentum_runner
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
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "experiments"))

from basket_backtest import execution_day, monthly_rebalance_dates, simulate_rebalanced  # noqa: E402
from engines.backtest_metrics import stationary_bootstrap_sharpe_ci  # noqa: E402
from engines.cost_model import CostModel  # noqa: E402
from momentum_12_1 import make_selectors  # noqa: E402
from oos_basket import _ir  # noqa: E402
from prices import point_in_time_adv  # noqa: E402

PROTOCOL_PATH = "research/MOMENTUM_12_1_PROTOCOL.md"
AMENDMENT_PATHS = [f"research/MOMENTUM_12_1_AMENDMENT_{i}.md" for i in (1, 2, 3)]
RUN_HISTORY = {
    "first_attempt": "Crashed before any return, eligibility count or result file was produced.",
    "cause": "Undefined session calendar included sparse and weekend rows; the held-price lookup did not skip NaN.",
    "amendment_1": "Defines the session calendar and prior-close carry that skips missing values.",
    "amendment_2": "Defines the first rebalance and abort gates without a grace period.",
    "amendment_3": "Defines earlier held-name ADV and missing execution-input handling.",
    "fix": "Filter all frames first; opt into earlier valid held inputs; count uses; enforce start and gates.",
}
UNIVERSE_DIR = REPO_ROOT / "data_snapshots" / "nse500-2026-11"
RESULT_PATH = REPO_ROOT / "research" / "momentum" / "result.json"
SPREAD_BPS = 30.0
BUDGET = 10_000_000.0
PERIODS_PER_YEAR = 12
N_BOOTSTRAP = 2000
MEAN_BLOCK = 3
SEED = 2026
CONFIDENCE = 0.95
GATE_INVESTED = (0.99, 1.00)
GATE_MIN_ELIGIBLE = 50


class AbortRun(RuntimeError):
    """An abort gate failed; no return statistics or result file are produced."""

    def __init__(self, message, diagnostics=None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_universe(path: Path) -> tuple[list[str], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = [ln for ln in lines if ln.startswith("#")]
    tickers = [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]
    return header, tickers


def load_frames(snapshot: Path, tickers: list[str]):
    """Frozen CSVs, each hash-checked against MANIFEST.json. Unavailable tickers are not substituted."""
    manifest = json.loads((snapshot / "MANIFEST.json").read_text())
    unavailable = manifest["unavailable"]
    close, opn, vol = {}, {}, {}
    for t in tickers:
        if t in unavailable:
            continue
        name = f"{t}.csv"
        path = snapshot / name
        entry = manifest["files"].get(name)
        if entry is None or not path.is_file() or sha256(path) != entry["sha256"]:
            raise RuntimeError(f"frozen snapshot missing or hash mismatch: {path}")
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df["Close"].dropna().empty:
            raise RuntimeError(f"{name} has no closes; list it as unavailable in the manifest")
        close[t], opn[t], vol[t] = df["Close"], df["Open"], df["Volume"]
    closes = pd.DataFrame(close).sort_index().astype(float)
    opens = pd.DataFrame(opn).reindex(closes.index).astype(float)
    volumes = pd.DataFrame(vol).reindex(closes.index).astype(float)  # NaN stays NaN: no fill
    return closes, opens, volumes, unavailable


def sessions(closes: pd.DataFrame) -> tuple[pd.DatetimeIndex, list[dict]]:
    """Amendment 1 calendar, using each name's unfiltered first/last close."""
    if not closes.index.is_unique or not closes.index.is_monotonic_increasing:
        raise ValueError("close dates must be unique and sorted")
    listed = pd.Series(0, index=closes.index)
    for sym in closes:
        valid = closes[sym].dropna()
        if not valid.empty:
            listed += ((closes.index >= valid.index[0]) & (closes.index <= valid.index[-1])).astype(int)
    counts = closes.notna().sum(axis=1)
    keep = (closes.index.dayofweek < 5) & (2 * counts >= listed)
    dropped = [{"date": d.date().isoformat(), "names_with_close": int(counts.at[d]),
                "listed_names": int(listed.at[d])} for d in closes.index[~keep]]
    return closes.index[keep], dropped


def run(closes: pd.DataFrame, opens: pd.DataFrame, volumes: pd.DataFrame, *,
        basket_select=None, benchmark_select=None) -> dict:
    """Filter the calendar, apply start/gates, simulate, then compute return statistics."""
    index, dropped = sessions(closes)
    closes, opens, volumes = (frame.loc[index] for frame in (closes, opens, volumes))
    first, end = closes.index.min().date(), closes.index.max().date()
    months_back = (end.year - first.year) * 12 + (end.month - first.month) + 1
    sched = monthly_rebalance_dates(closes, end, months_back=months_back)
    sel_b, sel_m, info = make_selectors(closes, volumes)
    skipped_start = []
    start = None
    for d in sched:
        if info(d)["eligible"] >= GATE_MIN_ELIGIBLE:
            start = d
            break
        skipped_start.append(d.isoformat())
    if start is None:
        raise ValueError("no month-end has at least 50 eligible names; run never starts")
    no_later = [d.isoformat() for d in sched if execution_day(closes, d) is None]
    active_sched = [d for d in sched if d >= start and execution_day(closes, d) is not None]
    diagnostics = {"session_count": len(index), "dropped_dates": dropped,
                   "first_rebalance": start.isoformat(), "skipped_month_ends_before_start": skipped_start,
                   "month_ends_no_later_session": no_later}

    def checked_select(select):
        def choose(c, d, eligible):
            n = info(d)["eligible"]
            if n < GATE_MIN_ELIGIBLE:
                raise AbortRun(f"eligible count at {d}: {n} < {GATE_MIN_ELIGIBLE}", diagnostics)
            return select(c, d, eligible)
        return choose

    def check(side):
        def check_row(row):
            f = row["invested_fraction"]
            if not (GATE_INVESTED[0] <= f <= GATE_INVESTED[1]):
                raise AbortRun(f"{side} invested fraction at {row['rebalance']}: {f!r} outside [0.99, 1.00]",
                               diagnostics)
        return check_row

    # The fallback must find a complete window on any earlier session, not just month-ends.
    adv_history = point_in_time_adv(closes, volumes, [d.date() for d in index])
    adv = {d: adv_history[d] for d in active_sched}
    kw = dict(cost_model=CostModel(brokerage_per_trade=0.0), budget=BUDGET, spread_bps=SPREAD_BPS,
              lookback=21, prior_close_carry=True, held_adv_history=adv_history, compute_period_returns=False)
    bt, bm = [], []
    basket = simulate_rebalanced(closes, opens, adv, active_sched,
                                select=checked_select(basket_select or sel_b), trace=bt,
                                check_rebalance=check("basket"), **kw)
    bench = simulate_rebalanced(closes, opens, adv, active_sched,
                               select=checked_select(benchmark_select or sel_m), trace=bm,
                               check_rebalance=check("benchmark"), **kw)
    b_dates = [d for d, _, _ in basket["baskets"]]
    if b_dates != active_sched or [d for d, _, _ in bench["baskets"]] != active_sched:
        raise RuntimeError("an executable rebalance was skipped; no registered rule covers this case")

    period_dates = b_dates[1:]
    b_ret = np.asarray([b["equity"] / a["equity"] - 1.0 for a, b in zip(bt, bt[1:])], dtype=float)
    m_ret = np.asarray([b["equity"] / a["equity"] - 1.0 for a, b in zip(bm, bm[1:])], dtype=float)
    assert len(period_dates) == len(b_ret) == len(m_ret)
    active = b_ret - m_ret
    ir = _ir(active)
    ci = stationary_bootstrap_sharpe_ci(active.tolist(), n_bootstrap=N_BOOTSTRAP, confidence=CONFIDENCE,
                                        mean_block_length=MEAN_BLOCK, periods_per_year=PERIODS_PER_YEAR,
                                        seed=SEED, risk_free=0.0)
    if abs(ci["sharpe"] - ir) > 1e-12:
        raise RuntimeError(f"bootstrap point {ci['sharpe']} != IR {ir}")
    lo, hi = float(ci["ci_lower"]), float(ci["ci_upper"])
    outcome = "Candidate" if lo > 0 else ("Not supported" if hi < 0 else "No evidence of an edge")

    def side_stats(trace, sim, rets):
        inv = [r["invested_fraction"] for r in trace]
        return {
            "standalone_ir": _ir(rets),
            "total_costs": float(sim["total_costs"]),
            "avg_turnover_after_entry": float(sim["avg_turnover_after_entry"]),
            "invested_min": min(inv), "invested_mean": sum(inv) / len(inv), "invested_max": max(inv),
            "carried_names": len(sim["carried"]), "skipped_buys": len(sim["skipped_buys"]),
            "final_equity": float(sim["final_equity"]),
            "amendment_3": {rule: {"count": len(uses), "uses": uses}
                            for rule, uses in sim["input_uses"].items()},
        }

    rows_per_date = []
    for idx, d in enumerate(b_dates):
        i = info(d)
        rows_per_date.append({
            "rebalance_date": d.isoformat(),
            "eligible_count": i["eligible"],
            "excluded_by_rule": i["failed"],
            "basket_size": basket["baskets"][idx][2],
            "benchmark_size": bench["baskets"][idx][2],
            "basket": {key: bt[idx][key] for key in ("invested_fraction", "turnover", "costs", "n_positions")},
            "benchmark": {key: bm[idx][key] for key in ("invested_fraction", "turnover", "costs", "n_positions")},
        })

    return {
        **diagnostics,
        "run_history": RUN_HISTORY,
        "amendment_3_month_end_no_later_session": {"count": len(no_later), "uses": no_later},
        "carried_count": len(basket["carried"]) + len(bench["carried"]),
        "params": {
            "signal": "close[t-21 sessions] / close[t-252 sessions] - 1",
            "selection": "top n_eligible // 5 by signal (ties: symbol ascending); benchmark all eligible",
            "eligibility": {"closes_complete_sessions": 253, "adv_sessions": 63, "adv_min_inr": 10_000_000,
                            "max_abs_move": 0.40, "moves_counted": "252 consecutive moves inside the 253-session window"},
            "sizing": "equal weight of current equity, fractional shares (simulate_rebalanced)",
            "schedule": "last session of each month; next-session open",
            "budget": BUDGET, "spread_bps": SPREAD_BPS,
            "cost_model": "CostModel(brokerage_per_trade=0.0), other defaults",
            "bootstrap": {"type": "stationary", "n_bootstrap": N_BOOTSTRAP, "mean_block": MEAN_BLOCK,
                          "seed": SEED, "confidence": CONFIDENCE, "periods_per_year": PERIODS_PER_YEAR,
                          "risk_free": 0.0},
            "gates": {"start": "first month-end with >= 50 eligible", "grace_period": 0,
                      "invested": list(GATE_INVESTED),
                      "min_eligible": GATE_MIN_ELIGIBLE},
        },
        "data_window": [first.isoformat(), end.isoformat()],
        "scheduled_month_ends": len(sched),
        "scheduled_first": sched[0].isoformat(), "scheduled_last": sched[-1].isoformat(),
        "actionable_first": b_dates[0].isoformat(), "actionable_last": b_dates[-1].isoformat(),
        "skipped_rebalances": {"basket": basket["skipped_rebalances"], "benchmark": bench["skipped_rebalances"]},
        "n_months": len(active),
        "monthly": [{"rebalance_date": d.isoformat(), "basket_net": float(b), "benchmark_net": float(m),
                     "active": float(b - m)} for d, b, m in zip(period_dates, b_ret, m_ret)],
        "ir": ir, "ci_lower": lo, "ci_upper": hi, "outcome": outcome,
        "basket": side_stats(bt, basket, b_ret),
        "benchmark": side_stats(bm, bench, m_ret),
        "per_date": rows_per_date,
        "eligible_count_min": min(r["eligible_count"] for r in rows_per_date),
        "eligible_count_max": max(r["eligible_count"] for r in rows_per_date),
        "eligible_count_median": float(np.median([r["eligible_count"] for r in rows_per_date])),
        "prediction": {"ir_between": [0.0, 0.6],
                       "chances": {"Candidate": 0.25, "No evidence of an edge": 0.70, "Not supported": 0.05}},
    }


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True).stdout.strip()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="12-1 momentum, Nifty 500 ex-AlphaCore (run once)")
    p.add_argument("--snapshot", type=Path, default=UNIVERSE_DIR)
    p.add_argument("--out", type=Path, default=RESULT_PATH)
    args = p.parse_args(argv)
    if args.out.exists():
        print(f"[REFUSED] {args.out} exists; the momentum run happens once", file=sys.stderr)
        return 2
    run_started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    header, tickers = read_universe(args.snapshot / "universe.txt")
    closes, opens, volumes, unavailable = load_frames(args.snapshot, tickers)
    try:
        res = run(closes, opens, volumes)
    except AbortRun as exc:
        print(f"[ABORT] gate failed, no return statistics computed: {exc}", file=sys.stderr)
        print(json.dumps(exc.diagnostics, indent=2), file=sys.stderr)
        return 3
    out = {
        "protocol": PROTOCOL_PATH,
        "protocol_commit": _git("log", "-1", "--format=%H", "--", PROTOCOL_PATH),
        "amendments": {path: _git("log", "-1", "--format=%H", "--", path) for path in AMENDMENT_PATHS},
        "code_commit": _git("rev-parse", "HEAD"),
        "code_dirty_tracked_files": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "run_timestamp_utc": run_started,
        "run_completed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "universe_file": str(args.snapshot.relative_to(REPO_ROOT) / "universe.txt"),
        "universe_sha256": sha256(args.snapshot / "universe.txt"),
        "universe_header": header,
        "manifest_sha256": sha256(args.snapshot / "MANIFEST.json"),
        "tickers_requested": len(tickers),
        "symbols_loaded": len(closes.columns),
        "unavailable": unavailable,
        **res,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "x", encoding="utf-8") as fh:
        fh.write(json.dumps(out, indent=2) + "\n")
    print(f"[MOMENTUM] months={out['n_months']} IR={out['ir']:.4f} "
          f"CI95=[{out['ci_lower']:.4f}, {out['ci_upper']:.4f}] outcome={out['outcome']}")
    print(f"[MOMENTUM] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
