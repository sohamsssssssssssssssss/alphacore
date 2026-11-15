"""
12-1 momentum: signal, eligibility and selection, per research/MOMENTUM_12_1_PROTOCOL.md.

signal:      close at t-21 sessions / close at t-252 sessions - 1, sessions on the closes index.
eligibility: (1) closes present for all 253 sessions t-252..t; (2) full 63-session point-in-time
             ADV >= 10,000,000; (3) no close-to-close move with |move| > 40% between consecutive
             sessions inside the 253-session window (252 moves).
selection:   basket = top n_eligible // 5 by signal, ties by symbol name ascending;
             benchmark = every eligible name.

Nothing here reads data after the rebalance date.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from prices import point_in_time_adv

SKIP_SESSIONS = 21
LOOKBACK_SESSIONS = 252
WINDOW_SESSIONS = 253
ADV_WINDOW_SESSIONS = 63
ADV_MIN = 10_000_000.0
MAX_ABS_MOVE = 0.40
K_FRACTION = 5
RULES = ("closes_complete_253", "adv_63_ge_10m", "no_move_over_40pct")


def _pos(closes: pd.DataFrame, d: date) -> int:
    ts = pd.Timestamp(d)
    if ts not in closes.index:
        raise ValueError(f"{d} is not a session on the closes index")
    return closes.index.get_loc(ts)


def signal(closes: pd.DataFrame, d: date) -> pd.Series:
    """12-1 return as of d. Uses only rows up to and including d."""
    pos = _pos(closes, d)
    if pos < LOOKBACK_SESSIONS:
        raise ValueError(f"{d} has fewer than {LOOKBACK_SESSIONS} prior sessions")
    past = closes.iloc[: pos + 1]
    return past.iloc[pos - SKIP_SESSIONS] / past.iloc[pos - LOOKBACK_SESSIONS] - 1.0


def eligibility(closes: pd.DataFrame, volumes: pd.DataFrame, d: date) -> tuple[set[str], dict]:
    """
    Eligible names as of d and the number of names failing each rule (not exclusive).
    The 253-session window is closes.iloc[pos-252 : pos+1]; no later row is read.
    """
    pos = _pos(closes, d)
    cols = list(closes.columns)
    if pos < LOOKBACK_SESSIONS:
        return set(), {"eligible": 0, "failed": {r: len(cols) for r in RULES}}
    win = closes.iloc[pos - LOOKBACK_SESSIONS: pos + 1]
    rule1 = win.notna().all()
    adv = point_in_time_adv(closes.iloc[: pos + 1], volumes.iloc[: pos + 1], [d])[d]
    rule2 = pd.Series({s: (s in adv and adv[s] >= ADV_MIN) for s in cols})
    moves = win.pct_change().iloc[1:]
    rule3 = ~(moves.abs() > MAX_ABS_MOVE).any()
    ok = rule1.astype(bool) & rule2.astype(bool) & rule3.astype(bool)
    eligible = {s for s in cols if bool(ok[s])}
    failed = {RULES[0]: int((~rule1.astype(bool)).sum()),
              RULES[1]: int((~rule2.astype(bool)).sum()),
              RULES[2]: int((~rule3.astype(bool)).sum())}
    return eligible, {"eligible": len(eligible), "failed": failed}


def make_selectors(closes: pd.DataFrame, volumes: pd.DataFrame):
    """
    Returns (basket_select, benchmark_select, info) for basket_backtest.simulate_rebalanced.
    info(d) gives the eligibility count and per-rule failure counts (memoised).
    """
    cache: dict[date, dict] = {}

    def info(d: date) -> dict:
        if d not in cache:
            elig, counts = eligibility(closes, volumes, d)
            cache[d] = {"eligible_set": elig, **counts}
        return cache[d]

    def ranked(d: date, eligible: set[str]) -> list[str]:
        elig = info(d)["eligible_set"] & eligible
        if not elig:  # also covers dates with too little history for the signal
            return []
        sig = signal(closes, d)
        return sorted(elig, key=lambda s: (-float(sig[s]), s))

    def basket_select(_closes, d, eligible):
        order = ranked(d, eligible)
        return order[: len(order) // K_FRACTION]

    def benchmark_select(_closes, d, eligible):
        return sorted(info(d)["eligible_set"] & eligible)

    return basket_select, benchmark_select, info
