from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

import forward_log


def _bars(n: int = 400, n_syms: int = 20, flat: bool = False, seed: int = 3):
    dates = pd.bdate_range("2023-01-02", periods=n)
    syms = [f"N{i:02d}" for i in range(n_syms)]
    if flat:
        closes = pd.DataFrame(100.0, index=dates, columns=syms)
    else:
        rng = np.random.default_rng(seed)
        rets = rng.normal(0.0005, 0.02, size=(n, n_syms))
        closes = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=dates, columns=syms)
    opens = closes.copy()
    volumes = pd.DataFrame(50_000.0, index=dates, columns=syms)
    return closes, opens, volumes


def _month_ends(closes: pd.DataFrame) -> list[date]:
    s = pd.Series(closes.index, index=closes.index)
    return [d.date() for d in s.groupby(closes.index.to_period("M")).max()]


def test_log_writes_basket_and_inputs_and_refuses_overwrite(tmp_path):
    bars = _bars()
    as_of = _month_ends(bars[0])[4]
    path = forward_log.log_month(as_of, bars, forward_dir=tmp_path)
    rec = json.loads(path.read_text())
    assert path.name == f"{as_of:%Y-%m}.json"
    assert rec["k"] == len(rec["basket"]) == 20 // 4
    assert set(rec["basket"]) <= set(rec["benchmark_members"]) <= set(rec["adv"])
    for key in ("universe_sha256", "bars_sha256", "code_commit", "protocol_commit"):
        assert rec["inputs"][key]
    with pytest.raises(FileExistsError):
        forward_log.log_month(as_of, bars, forward_dir=tmp_path)


def test_log_ignores_bars_after_as_of(tmp_path):
    closes, opens, volumes = _bars()
    as_of = _month_ends(closes)[4]
    a = json.loads(forward_log.log_month(as_of, (closes, opens, volumes), forward_dir=tmp_path / "a").read_text())
    closes2, opens2, volumes2 = closes.copy(), opens.copy(), volumes.copy()
    late = closes2.index > pd.Timestamp(as_of)
    closes2.loc[late] *= 50.0
    volumes2.loc[late] *= 50.0
    b = json.loads(forward_log.log_month(as_of, (closes2, opens2, volumes2), forward_dir=tmp_path / "b").read_text())
    for key in ("basket", "adv", "benchmark_members"):
        assert a[key] == b[key]
    assert a["inputs"]["bars_sha256"] == b["inputs"]["bars_sha256"]


def test_mark_needs_the_next_month_logged(tmp_path):
    bars = _bars()
    me = _month_ends(bars[0])
    forward_log.log_month(me[4], bars, forward_dir=tmp_path)
    with pytest.raises(FileNotFoundError, match="not logged yet"):
        forward_log.mark_month(f"{me[4]:%Y-%m}", bars, forward_dir=tmp_path)


def test_flat_prices_with_unchanged_basket_mark_to_zero_return(tmp_path):
    bars = _bars(flat=True)
    me = _month_ends(bars[0])
    forward_log.log_month(me[4], bars, forward_dir=tmp_path)
    forward_log.log_month(me[5], bars, forward_dir=tmp_path)
    out = forward_log.mark_month(f"{me[4]:%Y-%m}", bars, forward_dir=tmp_path)
    rec = json.loads(out.read_text())
    assert rec["net_return"] == 0.0
    assert rec["costs_at_period_end"] == 0.0  # same basket, so no trades at the next rebalance
    with pytest.raises(FileExistsError):
        forward_log.mark_month(f"{me[4]:%Y-%m}", bars, forward_dir=tmp_path)


def test_marks_chain_and_second_mark_requires_the_first(tmp_path):
    bars = _bars()
    me = _month_ends(bars[0])
    for d in me[4:7]:
        forward_log.log_month(d, bars, forward_dir=tmp_path)
    with pytest.raises(FileNotFoundError, match="mark"):
        forward_log.mark_month(f"{me[5]:%Y-%m}", bars, forward_dir=tmp_path)
    forward_log.mark_month(f"{me[4]:%Y-%m}", bars, forward_dir=tmp_path)
    out = forward_log.mark_month(f"{me[5]:%Y-%m}", bars, forward_dir=tmp_path)
    assert json.loads(out.read_text())["period_start_exec"] > json.loads(
        (tmp_path / f"{me[4]:%Y-%m}.marked.json").read_text())["period_start_exec"]


def test_missing_open_on_execution_day_raises_no_fallback(tmp_path):
    closes, opens, volumes = _bars()
    me = _month_ends(closes)
    forward_log.log_month(me[4], (closes, opens, volumes), forward_dir=tmp_path)
    forward_log.log_month(me[5], (closes, opens, volumes), forward_dir=tmp_path)
    exec_day = closes.index[closes.index > pd.Timestamp(me[4])][0]
    rec = json.loads((tmp_path / f"{me[4]:%Y-%m}.json").read_text())
    opens = opens.copy()
    opens.loc[exec_day, rec["basket"][0]] = np.nan
    with pytest.raises(ValueError, match="refusing to fall back to close"):
        forward_log.mark_month(f"{me[4]:%Y-%m}", (closes, opens, volumes), forward_dir=tmp_path)
