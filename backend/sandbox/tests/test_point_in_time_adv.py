from __future__ import annotations

import hashlib
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from basket_backtest import monthly_rebalance_dates, simulate
from prices import ADV_WINDOW_TRADING_DAYS, point_in_time_adv


def _synthetic(n_days: int = 700, n_syms: int = 30, seed: int = 7):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2019-01-01", periods=n_days)
    syms = [f"S{i:02d}" for i in range(n_syms)]
    rets = rng.normal(0.0005, 0.02, size=(n_days, n_syms))
    closes = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=dates, columns=syms)
    opens = closes * (1 + rng.normal(0, 0.003, size=closes.shape))
    volumes = pd.DataFrame(rng.integers(1_000, 100_000, size=closes.shape).astype(float),
                           index=dates, columns=syms)
    return closes, opens, volumes, syms


def test_adv_ignores_rows_after_rebalance_date():
    closes, _, volumes, _ = _synthetic()
    rb = closes.index[400].date()
    before = point_in_time_adv(closes, volumes, [rb])[rb]

    # Corrupt everything strictly after rb; ADV at rb must not move.
    closes2, volumes2 = closes.copy(), volumes.copy()
    closes2.iloc[401:] *= 1000.0
    volumes2.iloc[401:] *= 1000.0
    after = point_in_time_adv(closes2, volumes2, [rb])[rb]
    assert before == after


def test_adv_is_mean_of_close_times_volume_over_63_sessions_inclusive():
    closes, _, volumes, syms = _synthetic()
    rb = closes.index[300].date()
    got = point_in_time_adv(closes, volumes, [rb])[rb]
    window = slice(300 - ADV_WINDOW_TRADING_DAYS + 1, 301)  # 63 sessions ending on rb
    for s in syms:
        expected = float((closes[s].iloc[window] * volumes[s].iloc[window]).mean())
        assert got[s] == pytest.approx(expected, rel=1e-12)


def test_no_adv_without_a_full_63_session_window():
    closes, _, volumes, _ = _synthetic()
    early = closes.index[ADV_WINDOW_TRADING_DAYS - 2].date()  # only 62 sessions exist
    assert point_in_time_adv(closes, volumes, [early])[early] == {}


def test_symbol_with_gap_in_window_gets_no_adv():
    closes, _, volumes, _ = _synthetic()
    rb = closes.index[300].date()
    closes.iloc[280, closes.columns.get_loc("S00")] = np.nan
    got = point_in_time_adv(closes, volumes, [rb])[rb]
    assert "S00" not in got and "S01" in got


def test_simulate_with_adv_by_date_uses_point_in_time_values_and_raises_on_missing():
    closes, opens, volumes, syms = _synthetic()
    sched = monthly_rebalance_dates(closes, closes.index.max().date(), months_back=24)
    adv_by_date = point_in_time_adv(closes, volumes, sched)
    sched = [d for d in sched if adv_by_date[d]]
    res = simulate(closes, {}, opens, sched, adv_by_date=adv_by_date)
    assert res["total_costs"] > 0.0

    # A name with no point-in-time ADV is not rankable, so it is never bought
    # on a substituted cost. Its absence must not change the other names' trades.
    traded = res["baskets"][0][1][0]
    broken = {d: {s: v for s, v in m.items() if s != traded} for d, m in adv_by_date.items()}
    res2 = simulate(closes, {}, opens, sched, adv_by_date=broken)
    assert all(traded not in basket for _, basket, _ in res2["baskets"])


def test_legacy_path_output_unchanged():
    # Golden hash of simulate() on this synthetic set, recorded before the
    # adv_by_date change. Legacy callers must still get identical output.
    closes, opens, _, syms = _synthetic()
    adv = {s: 5e6 + 1e5 * i for i, s in enumerate(syms)}
    sched = monthly_rebalance_dates(closes, closes.index.max().date(), months_back=24)
    out = {str(k): simulate(closes, adv, opens, sched, k=k) for k in (None, 3, len(syms))}
    blob = json.dumps(out, default=str, sort_keys=True)
    assert hashlib.sha256(blob.encode()).hexdigest() == \
        "1698ccaa83b67152678d8d16e3df2bc08d4cd12ee09aa1f9d88c631890d15d50"
    assert all("total_costs" not in v for v in out.values())
