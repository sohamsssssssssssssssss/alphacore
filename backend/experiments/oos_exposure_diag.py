"""
Post-run exposure diagnostic. Read-only with respect to every registered result.

Re-executes the identical Arm A simulate calls (oos_basket.run_arm) with the
opt-in trace hook, after asserting that the period returns equal
research/oos/arm_a.json exactly. Also re-executes the K12 basket on the NSE
snapshot (legacy ADV path, existing parameters), after asserting equality with
research/v2/k12_basket.json. Records equity, cash, holdings value, invested
fraction and position count per rebalance. Writes:
    research/oos/arm_a_exposure.json
    research/oos/k12_exposure.json

Run from backend/:  python3.11 -m experiments.oos_exposure_diag
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

_BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "experiments"))

from basket_backtest import DEFAULT_BUDGET_INR, monthly_rebalance_dates, simulate  # noqa: E402
from oos_basket import BUDGET, LOOKBACK, SPREAD_BPS, load_snapshot, read_universe  # noqa: E402
from prices import ADV_WINDOW_TRADING_DAYS, point_in_time_adv  # noqa: E402
from universe import UNIVERSE_49  # noqa: E402

ARM_A_JSON = REPO_ROOT / "research" / "oos" / "arm_a.json"
ARM_A_EXPOSURE = REPO_ROOT / "research" / "oos" / "arm_a_exposure.json"
K12_JSON = REPO_ROOT / "research" / "v2" / "k12_basket.json"
K12_EXPOSURE = REPO_ROOT / "research" / "oos" / "k12_exposure.json"
NSE_SNAPSHOT = REPO_ROOT / "data_snapshots" / "2026-11"
US_SNAPSHOT = REPO_ROOT / "data_snapshots" / "us-2026-11"


def _rows(trace: list[dict]) -> list[dict]:
    out = []
    for e in trace:
        out.append({"rebalance": e["rebalance"], "exec_day": e["exec_day"], "equity": e["equity"],
                    "cash": e["cash"], "holdings_value": e["holdings_value"],
                    "invested_fraction": e["holdings_value"] / e["equity"], "n_positions": e["n_positions"]})
    return out


def _stats(rows: list[dict]) -> dict:
    f = [r["invested_fraction"] for r in rows]
    return {"first": f[0], "last": f[-1], "min": min(f), "mean": sum(f) / len(f), "max": max(f)}


def _pick(rows: list[dict], year: int) -> dict:
    """The actionable rebalance in December of `year` (the last one on file if none)."""
    hits = [r for r in rows if r["rebalance"].startswith(f"{year}-12")]
    return hits[0] if hits else None


def arm_a_trace() -> dict:
    header, tickers = read_universe(US_SNAPSHOT / "universe.txt")
    closes, opens, volumes, _ = load_snapshot(US_SNAPSHOT, tickers)
    first, end = closes.index.min().date(), closes.index.max().date()
    months_back = (end.year - first.year) * 12 + (end.month - first.month) + 1
    sched = monthly_rebalance_dates(closes, end, months_back=months_back)
    adv_by_date = point_in_time_adv(closes, volumes, sched, window=ADV_WINDOW_TRADING_DAYS)
    kw = dict(budget=BUDGET, spread_bps=SPREAD_BPS, lookback=LOOKBACK, adv_by_date=adv_by_date)
    bt_trace, bm_trace = [], []
    basket = simulate(closes, {}, opens, sched, k=None, trace=bt_trace, **kw)
    bench = simulate(closes, {}, opens, sched, k=len(closes.columns), trace=bm_trace, **kw)

    reg = json.loads(ARM_A_JSON.read_text())
    reg_b = [m["basket_net"] for m in reg["monthly"]]
    reg_m = [m["benchmark_net"] for m in reg["monthly"]]
    reg_dates = [m["rebalance_date"] for m in reg["monthly"]]
    assert basket["period_returns"] == reg_b, "basket period returns differ from arm_a.json"
    assert bench["period_returns"] == reg_m, "benchmark period returns differ from arm_a.json"
    assert [b[0].isoformat() for b in basket["baskets"][1:]] == reg_dates, "period dates differ"

    last = bm_trace[-1]
    top5 = sorted(last["position_values"].items(), key=lambda kv: kv[1], reverse=True)[:5]
    top5_weights = [{"symbol": s, "weight": v / last["holdings_value"]} for s, v in top5]
    return {"basket_rows": _rows(bt_trace), "benchmark_rows": _rows(bm_trace),
            "benchmark_top5_at_last_rebalance": top5_weights,
            "benchmark_last_rebalance_positions": len(last["position_values"])}


def nse_frames(snapshot: Path, symbols: list[str], as_of: date):
    """Same construction as prices.fetch_daily_bars, read from the frozen CSVs (no network)."""
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
    adv = {}
    for sym in symbols:
        win = merged[[f"{sym}_close", f"{sym}_vol"]].tail(ADV_WINDOW_TRADING_DAYS)
        tv = (win[f"{sym}_close"] * win[f"{sym}_vol"]).mean()
        adv[sym] = float(tv) if pd.notna(tv) else 0.0
    return closes, opens, adv


def k12_trace() -> dict:
    # fetch_daily_bars drops symbols with no data; the frozen snapshot has no CSV for TATAMOTORS.
    symbols = [s for s in UNIVERSE_49 if (NSE_SNAPSHOT / f"{s}.csv").exists()]
    dropped = sorted(set(UNIVERSE_49) - set(symbols))
    closes, opens, adv = nse_frames(NSE_SNAPSHOT, symbols, date(2026, 8, 13))
    end = closes.index.max().date()
    sched = monthly_rebalance_dates(closes, end)
    trace: list = []
    res = simulate(closes, adv, opens, sched, budget=DEFAULT_BUDGET_INR, spread_bps=10.0, k=None,
                   lookback=21, trace=trace)
    ref = json.loads(K12_JSON.read_text())["raw_backtest"]["period_returns"]
    assert res["period_returns"] == ref, "K12 period returns differ from research/v2/k12_basket.json"
    return {"rows": _rows(trace), "n_period_returns": len(res["period_returns"]), "dropped_no_csv": dropped,
            "n_symbols": len(symbols)}


def main() -> int:
    arm = arm_a_trace()
    arm_b, arm_m = arm["basket_rows"], arm["benchmark_rows"]
    print("ARM A: period returns equal arm_a.json exactly (basket and benchmark): PASS")
    for label, rows in (("basket", arm_b), ("benchmark", arm_m)):
        s = _stats(rows)
        print(f"[ARM A {label}] invested fraction first {rows[0]['rebalance']}={s['first']:.4f} "
              f"last {rows[-1]['rebalance']}={s['last']:.4f} min={s['min']:.4f} mean={s['mean']:.4f} max={s['max']:.4f}")
        for y in (2012, 2015, 2018, 2021, 2024):
            r = _pick(rows, y)
            if r:
                print(f"[ARM A {label}] {r['rebalance']} invested={r['invested_fraction']:.4f} "
                      f"positions={r['n_positions']}")
    print("[ARM A benchmark] top 5 weights at last rebalance "
          f"({arm['benchmark_last_rebalance_positions']} positions):")
    for t in arm["benchmark_top5_at_last_rebalance"]:
        print(f"    {t['symbol']} {t['weight']:.4f}")

    k12 = k12_trace()
    ks = _stats(k12["rows"])
    print(f"K12: period returns equal k12_basket.json exactly ({k12['n_period_returns']} periods): PASS")
    print(f"[K12] invested fraction first={ks['first']:.4f} last={ks['last']:.4f} "
          f"min={ks['min']:.4f} mean={ks['mean']:.4f} max={ks['max']:.4f}")

    ARM_A_EXPOSURE.parent.mkdir(parents=True, exist_ok=True)
    with open(ARM_A_EXPOSURE, "x", encoding="utf-8") as fh:
        fh.write(json.dumps({"source": "research/oos/arm_a.json (period returns asserted equal)",
                             "basket": {"stats": _stats(arm_b), "rebalances": arm_b},
                             "benchmark": {"stats": _stats(arm_m), "rebalances": arm_m},
                             "benchmark_top5_at_last_rebalance": arm["benchmark_top5_at_last_rebalance"]},
                            indent=2) + "\n")
    with open(K12_EXPOSURE, "x", encoding="utf-8") as fh:
        fh.write(json.dumps({"source": "research/v2/k12_basket.json (period returns asserted equal)",
                             "stats": ks, "rebalances": k12["rows"]}, indent=2) + "\n")
    print(f"wrote {ARM_A_EXPOSURE}\nwrote {K12_EXPOSURE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
