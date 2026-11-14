"""
Arm B scaffold: forward paper log for the locked basket on the 49-symbol NSE universe.
Specification: research/OOS_BASKET_PROTOCOL.md, "Arm B".

log  --as-of DATE    writes research/forward/YYYY-MM.json for the rebalance on DATE:
                     basket, point-in-time ADV, benchmark members, input hashes.
                     Refuses to overwrite an existing month.
mark --month YYYY-MM marks that month to market once the NEXT month is logged.
                     Fills use next-session opens, with CostModel costs and the
                     same delta-trading rules as basket_backtest.simulate.
                     Writes research/forward/YYYY-MM.marked.json. Refuses to overwrite.

Fills mirror simulate(). The differences are deliberate: a missing open raises
(no fallback to close), and an ADV gap raises (no substitute). Marks chain,
so each month starts from the portfolio state the previous mark ended with.

Nothing here runs on import. Real month entries are generated only by running
the log command.

Run from backend/ (python3.11):
    python3.11 -m experiments.forward_log log --as-of 2026-11-30
    python3.11 -m experiments.forward_log mark --month 2026-11
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

_BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = _BACKEND.parent
FORWARD_DIR = REPO_ROOT / "research" / "forward"
PROTOCOL_PATH = "research/OOS_BASKET_PROTOCOL.md"
sys.path.insert(0, str(_BACKEND))  # engines.*
sys.path.insert(0, str(_BACKEND / "experiments"))  # basket_backtest (wires sandbox/)

from basket_backtest import ASSUMED_SPREAD_BPS, DEFAULT_BUDGET_INR, top_quartile  # noqa: E402
from engines.cost_model import CostModel  # noqa: E402
from prices import ADV_WINDOW_TRADING_DAYS, _download_one, point_in_time_adv  # noqa: E402
from rs_signal import LOOKBACK_TRADING_DAYS, rank_table  # noqa: E402
from universe import UNIVERSE_49  # noqa: E402

PARAMS = {
    "lookback_sessions": LOOKBACK_TRADING_DAYS,
    "k_rule": "n_ranked // 4",
    "budget": DEFAULT_BUDGET_INR,
    "spread_bps": ASSUMED_SPREAD_BPS,
    "adv_window_sessions": ADV_WINDOW_TRADING_DAYS,
    "eligibility": "full point-in-time ADV window at the rebalance",
    "cost_model": "engines.cost_model.CostModel() defaults",
}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True).stdout.strip()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_bars(through: date, history_days: int = 400):
    """Live NSE bars (close, open, volume) for UNIVERSE_49 through `through`. Network call."""
    start = (through - timedelta(days=history_days)).isoformat()
    end = (through + timedelta(days=1)).isoformat()
    cols: dict[str, dict[str, pd.Series]] = {"close": {}, "open": {}, "volume": {}}
    for sym in UNIVERSE_49:
        _, df = _download_one(sym, start, end, include_open=True)
        if df is None:
            continue
        for c in cols:
            cols[c][sym] = df[c]
    closes = pd.DataFrame(cols["close"]).sort_index()
    opens = pd.DataFrame(cols["open"]).reindex(closes.index)
    volumes = pd.DataFrame(cols["volume"]).reindex(closes.index)
    return closes, opens, volumes


def _bars_sha(bars, through: date) -> str:
    h = hashlib.sha256()
    for frame in bars:
        h.update(frame[frame.index <= pd.Timestamp(through)].to_csv().encode())
    return h.hexdigest()


def _next_session(closes: pd.DataFrame, day: date) -> date | None:
    later = closes.index[closes.index > pd.Timestamp(day)]
    return later[0].date() if len(later) else None


def _next_month(month: str) -> str:
    y, m = map(int, month.split("-"))
    return f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"


def _prev_month(month: str) -> str:
    y, m = map(int, month.split("-"))
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def log_month(as_of: date, bars, forward_dir: Path = FORWARD_DIR) -> Path:
    """Write the basket for the rebalance on `as_of`. Refuses to overwrite the month."""
    closes, opens, volumes = (f[f.index <= pd.Timestamp(as_of)] for f in bars)
    if pd.Timestamp(as_of) not in closes.index:
        raise ValueError(f"{as_of} is not a session in the data")
    # shortcut: the "last session of month" rule is not checked here (it needs an NSE holiday calendar
    # the repo does not have); the caller picks the date. Upgrade when a holiday calendar is added.
    adv = point_in_time_adv(closes, volumes, [as_of])[as_of]
    eligible = set(adv)
    basket = top_quartile(closes, as_of, lookback=LOOKBACK_TRADING_DAYS, eligible=eligible)
    if not basket:
        raise ValueError(f"no rankable names at {as_of}")
    benchmark = [s for s, row in rank_table(closes, as_of, lookback=LOOKBACK_TRADING_DAYS).iterrows()
                 if bool(row["has_data"]) and s in eligible]
    month = as_of.strftime("%Y-%m")
    record = {
        "month": month,
        "as_of": as_of.isoformat(),
        "basket": basket,
        "k": len(basket),
        "benchmark_members": benchmark,
        "adv": adv,
        "universe": UNIVERSE_49,
        "params": PARAMS,
        "inputs": {
            "universe_sha256": _sha("\n".join(UNIVERSE_49).encode()),
            "bars_sha256": _bars_sha(bars, as_of),
            "bars_through": as_of.isoformat(),
            "code_commit": _git("rev-parse", "HEAD"),
            "protocol_commit": _git("log", "-1", "--format=%H", "--", PROTOCOL_PATH),
        },
        "logged_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    forward_dir.mkdir(parents=True, exist_ok=True)
    path = forward_dir / f"{month}.json"
    with open(path, "x", encoding="utf-8") as fh:  # mode "x" refuses to overwrite
        fh.write(json.dumps(record, indent=2) + "\n")
    return path


def _open(opens: pd.DataFrame, sym: str, day: date) -> float:
    price = opens.at[pd.Timestamp(day), sym] if sym in opens.columns else float("nan")
    if not price or price != price or price <= 0:  # NaN or non-positive
        raise ValueError(f"no open price for {sym} on {day}; refusing to fall back to close")
    return float(price)


def _adv(rec: dict, sym: str) -> float:
    if sym not in rec["adv"]:
        raise ValueError(f"no point-in-time ADV for {sym} at {rec['as_of']}; refusing to substitute")
    return rec["adv"][sym]


def _fill(state: dict, rec: dict, opens: pd.DataFrame, day: date, cm: CostModel) -> tuple[dict, float]:
    """Delta fills at `day`'s open, mirroring simulate(). Returns (new state, costs paid)."""
    holdings = dict(state["holdings"])
    cash = float(state["cash"])
    prev = set(state["basket"])
    new = set(rec["basket"])
    per_position = DEFAULT_BUDGET_INR / max(len(rec["basket"]), 1)
    buy_n = buy_c = sell_n = sell_c = 0.0
    for sym in sorted(new - prev):
        price = _open(opens, sym, day)
        qty = max(1, int(per_position // price))
        holdings[sym] = float(qty)
        buy_n += qty * price
        buy_c += cm.total_cost(price=price, qty=float(qty), adv=_adv(rec, sym), spread_bps=ASSUMED_SPREAD_BPS, side="BUY")
    for sym in sorted(prev - new):
        qty = holdings.pop(sym, 0.0)
        if qty <= 0:
            continue
        price = _open(opens, sym, day)
        sell_n += qty * price
        sell_c += cm.total_cost(price=price, qty=qty, adv=_adv(rec, sym), spread_bps=ASSUMED_SPREAD_BPS, side="SELL")
    cash = cash + sell_n - sell_c - buy_n - buy_c
    return {"holdings": holdings, "cash": cash, "basket": sorted(new)}, buy_c + sell_c


def _value(state: dict, opens: pd.DataFrame, day: date) -> float:
    return state["cash"] + sum(qty * _open(opens, sym, day) for sym, qty in state["holdings"].items())


def mark_month(month: str, bars, forward_dir: Path = FORWARD_DIR) -> Path:
    """Mark `month` to market at next-session opens. Needs the next month logged. Refuses to overwrite."""
    closes, opens, _ = bars
    cur_path = forward_dir / f"{month}.json"
    nxt_path = forward_dir / f"{_next_month(month)}.json"
    if not nxt_path.exists():
        raise FileNotFoundError(f"{nxt_path.name} not logged yet; mark {month} after the next rebalance is logged")
    cur, nxt = _load(cur_path), _load(nxt_path)
    exec_cur = _next_session(closes, date.fromisoformat(cur["as_of"]))
    exec_nxt = _next_session(closes, date.fromisoformat(nxt["as_of"]))
    if exec_cur is None or exec_nxt is None:
        raise RuntimeError(f"next-session opens for {month} are not in the data yet")

    cm = CostModel()
    prev_marked = forward_dir / f"{_prev_month(month)}.marked.json"
    if (forward_dir / f"{_prev_month(month)}.json").exists():
        if not prev_marked.exists():
            raise FileNotFoundError(f"mark {_prev_month(month)} first; marks chain")
        base = _load(prev_marked)["state_at_period_end"]  # already holds this month's entry fills
        costs_in = _load(prev_marked)["costs_at_period_end"]
    else:
        base, costs_in = _fill({"holdings": {}, "cash": DEFAULT_BUDGET_INR, "basket": []}, cur, opens, exec_cur, cm)
    eq_start = _value(base, opens, exec_cur)
    state_end, costs_out = _fill(base, nxt, opens, exec_nxt, cm)
    eq_end = _value(state_end, opens, exec_nxt)

    record = {
        "month": month,
        "basket": cur["basket"],
        "period_start_exec": exec_cur.isoformat(),
        "period_end_exec": exec_nxt.isoformat(),
        "next_month": _next_month(month),
        "costs_at_start": costs_in,
        "costs_at_period_end": costs_out,
        "equity_at_start": eq_start,
        "equity_at_period_end": eq_end,
        "net_return": eq_end / eq_start - 1.0,
        "state_at_period_end": state_end,
        "inputs": {
            "bars_sha256": _bars_sha(bars, exec_nxt),
            "log_sha256": _sha(cur_path.read_bytes()),
            "next_log_sha256": _sha(nxt_path.read_bytes()),
            "code_commit": _git("rev-parse", "HEAD"),
        },
        "marked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    out = forward_dir / f"{month}.marked.json"
    with open(out, "x", encoding="utf-8") as fh:  # mode "x" refuses to overwrite
        fh.write(json.dumps(record, indent=2) + "\n")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Arm B forward paper log (scaffold)")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("log", help="write research/forward/YYYY-MM.json for a rebalance date")
    a.add_argument("--as-of", required=True, type=date.fromisoformat)
    m = sub.add_parser("mark", help="mark the given month to market at next-session opens")
    m.add_argument("--month", required=True, help="YYYY-MM")
    args = p.parse_args(argv)
    if args.cmd == "log":
        path = log_month(args.as_of, load_bars(args.as_of))
    else:
        path = mark_month(args.month, load_bars(date.today()))
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
