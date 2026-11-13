"""Regime attribution: why did 2020-2023 outperform 2023-2026?

Diagnostic only — reuses the Phase 2 cached dataset (/tmp/p2_full.pkl) and
the unmodified basket_backtest.simulate() output. No strategy or parameter
changes. Three checks, in the brief's order:

  A) NOISE: stationary-bootstrap null for the H1-vs-H2 Sharpe gap.
  B) MARKET REGIME: realized vol / dispersion / direction per half.
  C) SIGNAL DECAY: rolling 12-period win-alignment and basket gross returns.

Run from backend/:
    python3.11 -m sandbox.regime_diagnostic [--cache /tmp/p2_full.pkl]
"""

from __future__ import annotations

import argparse
import math
import os
import pickle
import sys
from datetime import date

import numpy as np
import pandas as pd

_SANDBOX_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_SANDBOX_DIR), "experiments"))
if _SANDBOX_DIR not in sys.path:
    sys.path.insert(0, _SANDBOX_DIR)
_BACKEND = os.path.dirname(_SANDBOX_DIR)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from basket_backtest import simulate, monthly_rebalance_dates  # noqa: E402
from engines.backtest_metrics import compute_sharpe  # noqa: E402

H1_END = date(2023, 8, 13)   # Phase 2 H1 as_of / H2 start boundary
OBSERVED_GAP = 1.1387 - 0.3928  # H1 Sharpe - H2 Sharpe (Phase 2 report)


# ---------------------------------------------------------------------------
# Shared data: reload the Phase 2 cache, reproduce the center-period series
# ---------------------------------------------------------------------------

def load_center(cache_path: str) -> dict:
    with open(cache_path, "rb") as fh:
        blob = pickle.load(fh)
    closes, adv, opens = blob["closes"], blob["adv"], blob["opens"]
    end = closes.index.max().date()
    schedule = monthly_rebalance_dates(closes, end)  # Phase 2 center: no --start
    res = simulate(closes, adv, opens, schedule, budget=1_000_000.0,
                   spread_bps=10.0, k=None, lookback=21)
    return {"closes": closes, "adv": adv, "opens": opens, "res": res, "end": end}


# ---------------------------------------------------------------------------
# PART A — noise check: stationary-bootstrap null for the Sharpe gap
# ---------------------------------------------------------------------------

def _stationary_resample(series: np.ndarray, n: int, p: float, rng: np.random.Generator) -> np.ndarray:
    """One stationary-bootstrap resample (geometric blocks) of length n."""
    sample = np.empty(n, dtype=float)
    pos = 0
    start = int(rng.integers(0, len(series)))
    while pos < n:
        block_len = int(np.ceil(rng.geometric(p)))
        block_len = min(block_len, n - pos)
        for j in range(block_len):
            sample[pos] = series[(start + j) % len(series)]
            pos += 1
        start = int(rng.integers(0, len(series)))
    return sample


def part_a(period_returns: list[float], n_bootstrap: int = 5000) -> dict:
    arr = np.asarray(period_returns, dtype=float)
    n = arr.size
    rng = np.random.default_rng(42)  # same seed convention as the repo CI
    p = 1.0 / 10.0  # mean block length 10 (same as stationary_bootstrap_sharpe_ci)

    abs_gaps: list[float] = []
    dir_gaps: list[float] = []
    for _ in range(n_bootstrap):
        resample = _stationary_resample(arr, n, p, rng)
        # random disjoint 34/35 split of the resample (34+35 < n; one obs unused)
        idx = rng.permutation(n)
        a = resample[idx[:34]]
        b = resample[idx[34:34 + 35]]
        sa = compute_sharpe(list(a), periods_per_year=12)
        sb = compute_sharpe(list(b), periods_per_year=12)
        abs_gaps.append(abs(sa - sb))
        dir_gaps.append(sa - sb)

    abs_arr = np.array(abs_gaps)
    dir_arr = np.array(dir_gaps)
    frac_abs = float(np.mean(abs_arr >= OBSERVED_GAP))
    frac_dir = float(np.mean(dir_arr >= OBSERVED_GAP))
    return {
        "observed_gap": OBSERVED_GAP,
        "n_periods_full": n,
        "n_bootstrap": n_bootstrap,
        "frac_abs_gap_ge_observed": frac_abs,
        "frac_directed_gap_ge_observed": frac_dir,
        "median_abs_gap": float(np.median(abs_arr)),
        "p90_abs_gap": float(np.percentile(abs_arr, 90)),
        "p99_abs_gap": float(np.percentile(abs_arr, 99)),
        "null_abs_gap_mean": float(abs_arr.mean()),
    }


# ---------------------------------------------------------------------------
# PART B — market regime per half
# ---------------------------------------------------------------------------

def _half_mask(closes: pd.DataFrame, h2: bool) -> np.ndarray:
    return closes.index > pd.Timestamp(H1_END) if h2 else closes.index <= pd.Timestamp(H1_END)


def _ew_daily_returns(closes: pd.DataFrame) -> pd.Series:
    """Equal-weight universe daily returns (row mean across symbols)."""
    rets = closes.pct_change()
    return rets.mean(axis=1, skipna=True).dropna()


def _realized_vol_annualized(daily: pd.Series) -> float:
    return float(daily.std(ddof=1) * math.sqrt(252))


def _monthly_dispersion(closes: pd.DataFrame) -> pd.Series:
    """Cross-sectional std of monthly (month-end close-to-close) returns per month."""
    monthly_last = closes.resample("ME").last()
    monthly_ret = monthly_last.pct_change()
    return monthly_ret.std(axis=1, skipna=True).dropna()


def part_b(closes: pd.DataFrame) -> dict:
    daily = _ew_daily_returns(closes)
    h1 = daily.index <= pd.Timestamp(H1_END)
    h2 = daily.index > pd.Timestamp(H1_END)

    out = {}
    for label, mask in (("H1", h1), ("H2", h2)):
        d = daily[mask]
        total = float((1.0 + d).prod() - 1.0)
        years = len(d) / 252.0
        ann = float((1.0 + total) ** (1.0 / years) - 1.0) if years > 0 else 0.0
        out[label] = {
            "realized_vol_ann_pct": _realized_vol_annualized(d) * 100.0,
            "universe_total_return_pct": total * 100.0,
            "universe_annualized_return_pct": ann * 100.0,
            "n_days": int(len(d)),
        }

    disp = _monthly_dispersion(closes)
    out["dispersion"] = {}
    for label, lo, hi in (("H1", pd.Timestamp("2020-08-31"), pd.Timestamp("2023-08-31")),
                          ("H2", pd.Timestamp("2023-09-30"), pd.Timestamp("2026-07-31"))):
        sel = disp[(disp.index >= lo) & (disp.index <= hi)]
        out["dispersion"][label] = {
            "n_months": int(len(sel)),
            "mean_cs_std_pct": float(sel.mean() * 100.0),
        }
    return out


# ---------------------------------------------------------------------------
# PART C — signal decay: rolling win-alignment and basket gross returns
# ---------------------------------------------------------------------------

def part_c(res: dict) -> dict:
    baskets = res["baskets"]                      # (rb, basket, size) per actionable rebalance
    bg = res["basket_gross_returns"]              # aligned: bg[i] is the period ENDING at baskets[i+1]
    ug = res["universe_gross_returns"]
    wins = [1.0 if b > u else 0.0 for b, u in zip(bg, ug)]
    # ending rebalance date per period: period i ends at baskets[i+1].rb
    end_dates = [baskets[i + 1][0] for i in range(len(bg))]

    rows = []
    for i in range(len(bg)):
        win12 = sum(wins[max(0, i - 11):i + 1]) / len(wins[max(0, i - 11):i + 1])
        gross12 = sum(bg[max(0, i - 11):i + 1]) / len(bg[max(0, i - 11):i + 1])
        rows.append({
            "period_end": end_dates[i].isoformat(),
            "win_alignment_12m_pct": round(win12 * 100.0, 1),
            "basket_gross_12m_pct": round(gross12 * 100.0, 2),
            "basket_gross_1m_pct": round(bg[i] * 100.0, 2),
        })

    # trend diagnostics
    idx = np.arange(len(bg))
    slope_win, _ = np.polyfit(idx, [r["win_alignment_12m_pct"] for r in rows], 1)
    slope_gross, _ = np.polyfit(idx, [r["basket_gross_12m_pct"] for r in rows], 1)
    h1_mask = np.array([d <= H1_END for d in end_dates])
    h2_mask = ~h1_mask
    win_h1 = np.mean([wins[i] for i in range(len(wins)) if h1_mask[i]])
    win_h2 = np.mean([wins[i] for i in range(len(wins)) if h2_mask[i]])
    gross_h1 = np.mean([bg[i] for i in range(len(bg)) if h1_mask[i]])
    gross_h2 = np.mean([bg[i] for i in range(len(bg)) if h2_mask[i]])

    return {
        "rows": rows,
        "rolling_win_slope_per_period_pp": float(slope_win),
        "rolling_gross_slope_per_period_pp": float(slope_gross),
        "win_rate_h1_pct": float(win_h1 * 100.0),
        "win_rate_h2_pct": float(win_h2 * 100.0),
        "gross_h1_pct": float(gross_h1 * 100.0),
        "gross_h2_pct": float(gross_h2 * 100.0),
        "n_h1_periods": int(h1_mask.sum()),
        "n_h2_periods": int(h2_mask.sum()),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", default="/tmp/p2_full.pkl")
    p.add_argument("--n-bootstrap", type=int, default=5000)
    args = p.parse_args(argv)

    data = load_center(args.cache)
    res = data["res"]
    pr = res["period_returns"]

    # Reproducibility gate: must match the Phase 2 center run exactly.
    sr = compute_sharpe(pr, periods_per_year=12)
    print(f"[DATA] full-period series: {len(pr)} period returns, "
          f"sharpe={sr:.4f}, final_equity={res['final_equity']:,.0f}, "
          f"win_alignment={res['win_alignment_pct']:.1f}%")
    print(f"[DATA] expected (Phase 2 center): sharpe=0.6610, final_equity=2,121,533, win_alignment=45.7%")

    print("\n" + "=" * 70)
    print("PART A — NOISE CHECK (stationary bootstrap, block=10, seed=42, n=%d)" % args.n_bootstrap)
    print("=" * 70)
    a = part_a(pr, n_bootstrap=args.n_bootstrap)
    print(f"  observed |H1 - H2| Sharpe gap:  {a['observed_gap']:.4f}")
    print(f"  null distribution of |gap|:      mean={a['null_abs_gap_mean']:.4f} "
          f"median={a['median_abs_gap']:.4f} p90={a['p90_abs_gap']:.4f} p99={a['p99_abs_gap']:.4f}")
    print(f"  P(|gap| >= observed) [two-sided]: {a['frac_abs_gap_ge_observed']:.4f} "
          f"({a['frac_abs_gap_ge_observed'] * 100:.1f}%)")
    print(f"  P(directed gap >= observed)      : {a['frac_directed_gap_ge_observed']:.4f} "
          f"({a['frac_directed_gap_ge_observed'] * 100:.1f}%)")

    print("\n" + "=" * 70)
    print("PART B — MARKET REGIME CHECK (equal-weight 48-symbol universe, cached closes)")
    print("=" * 70)
    b = part_b(data["closes"])
    print(f"  {'metric':<34}{'H1 (2020-08 -> 2023-08)':>24}{'H2 (2023-08 -> 2026-08)':>24}")
    for key, label in (("realized_vol_ann_pct", "realized vol (ann, %)" ),
                       ("universe_total_return_pct", "equal-weight total return (%)"),
                       ("universe_annualized_return_pct", "equal-weight ann. return (%)"),
                       ("n_days", "trading days")):
        print(f"  {label:<34}{b['H1'][key]:>24.4f}{b['H2'][key]:>24.4f}")
    print(f"  {'monthly cross-sectional std (dispersion)':<34}"
          f"{b['dispersion']['H1']['mean_cs_std_pct']:>24.4f}{b['dispersion']['H2']['mean_cs_std_pct']:>24.4f}")

    print("\n" + "=" * 70)
    print("PART C — SIGNAL DECAY (rolling 12-period, full window)")
    print("=" * 70)
    c = part_c(res)
    print(f"  H1 periods={c['n_h1_periods']} win-rate={c['win_rate_h1_pct']:.1f}% "
          f"avg gross={c['gross_h1_pct']:.2f}% | H2 periods={c['n_h2_periods']} "
          f"win-rate={c['win_rate_h2_pct']:.1f}% avg gross={c['gross_h2_pct']:.2f}%")
    print(f"  rolling-12m win-alignment slope: {c['rolling_win_slope_per_period_pp']:.3f} pp/period")
    print(f"  rolling-12m gross-return slope:  {c['rolling_gross_slope_per_period_pp']:.4f} pp/period")
    print("  period_end, win_align_12m%, basket_gross_12m%, basket_gross_1m%")
    for r in c["rows"]:
        print(f"  {r['period_end']}, {r['win_alignment_12m_pct']:.1f}, "
              f"{r['basket_gross_12m_pct']:.2f}, {r['basket_gross_1m_pct']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
