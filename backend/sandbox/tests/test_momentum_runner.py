from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import momentum_12_1 as mom
import momentum_runner as mr


def _panel(n_days: int, n_syms: int = 20, seed: int = 4):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-01", periods=n_days)
    syms = [f"N{i:02d}" for i in range(n_syms)]
    rets = rng.normal(0.0003, 0.012, size=(n_days, n_syms))
    closes = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=dates, columns=syms)
    opens = closes * (1 + rng.normal(0, 0.002, size=closes.shape))
    volumes = pd.DataFrame(2e5, index=dates, columns=syms)
    return closes, opens, volumes


def test_identical_selectors_give_exactly_zero_active_returns_and_outcome_no_evidence(monkeypatch):
    monkeypatch.setattr(mr, "GATE_MIN_ELIGIBLE", 5)
    closes, opens, volumes = _panel(n_days=700)
    sel, _, _ = mom.make_selectors(closes, volumes)
    res = mr.run(closes, opens, volumes, basket_select=sel, benchmark_select=sel)
    assert res["n_months"] > 10
    assert all(m["active"] == 0.0 for m in res["monthly"])
    assert res["ir"] == 0.0
    assert res["outcome"] == "No evidence of an edge"


def test_run_is_deterministic(monkeypatch):
    monkeypatch.setattr(mr, "GATE_MIN_ELIGIBLE", 5)
    closes, opens, volumes = _panel(n_days=700)
    a = mr.run(closes, opens, volumes)
    b = mr.run(closes, opens, volumes)
    assert a == b


def test_calendar_counts_listed_names_and_filters_weekends_and_thin_weekdays():
    dates = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-04", "2020-01-06",
                            "2020-01-07", "2020-01-08"])
    c = pd.DataFrame(100.0, index=dates, columns=list("ABCD"))
    c.loc[dates[0], ["C", "D"]] = np.nan  # not listed yet; two of two
    c.loc[dates[3], ["B", "C", "D"]] = np.nan  # one of four: drop
    c.loc[dates[4], ["C", "D"]] = np.nan  # exactly half: keep
    index, dropped = mr.sessions(c)
    assert list(index) == list(dates[[0, 1, 4, 5]])
    assert dropped == [
        {"date": "2020-01-04", "names_with_close": 4, "listed_names": 4},
        {"date": "2020-01-06", "names_with_close": 1, "listed_names": 4},
    ]


def test_lags_and_completeness_count_filtered_sessions():
    c, o, v = _panel(400)
    thin = c.index[100]
    c.loc[thin, c.columns[1:]] = np.nan
    weekend = pd.Timestamp("2018-06-02")
    c.loc[weekend] = 900.0
    c = c.sort_index()
    index, _ = mr.sessions(c)
    filtered = c.loc[index]
    d = index[300].date()
    sig = mom.signal(filtered, d)
    pd.testing.assert_series_equal(sig, filtered.iloc[279] / filtered.iloc[48] - 1.0)
    filtered = filtered.copy()
    filtered.iloc[200, 0] = np.nan
    eligible, counts = mom.eligibility(filtered, v.loc[index], d)
    assert "N00" not in eligible
    assert counts["failed"]["closes_complete_253"] == 1


def test_calendar_is_applied_to_all_frames_before_windows_and_schedule(monkeypatch):
    c, o, v = _panel(400, n_syms=50)
    baseline = mr.run(c, o, v)
    weekend = pd.Timestamp("2018-06-02")
    for frame in (c, o, v):
        frame.loc[weekend] = 1.0
        frame.sort_index(inplace=True)
    actual = mr.run(c, o, v)
    assert actual["monthly"] == baseline["monthly"]
    assert actual["per_date"] == baseline["per_date"]
    assert actual["session_count"] == 400
    assert actual["dropped_dates"][0]["date"] == "2018-06-02"


def test_start_is_first_month_end_with_at_least_50_and_last_without_execution_is_skipped():
    c, o, v = _panel(400, n_syms=50)
    c.iloc[:30, 0] = np.nan
    sched = mr.monthly_rebalance_dates(c, c.index[-1].date(), months_back=24)
    expected = next(d for d in sched if c.index.get_loc(pd.Timestamp(d)) >= 282)
    result = mr.run(c, o, v)
    assert result["first_rebalance"] == expected.isoformat()
    assert result["skipped_month_ends_before_start"] == [d.isoformat() for d in sched if d < expected]
    assert result["eligible_count_min"] == 50
    assert result["amendment_3_month_end_no_later_session"] == {
        "count": 1, "uses": [c.index[-1].date().isoformat()]}
    assert result["actionable_last"] == sched[-2].isoformat()


@pytest.mark.parametrize("side,value", [("basket", 0.989), ("basket", 1.001),
                                        ("benchmark", 0.989), ("benchmark", 1.001)])
def test_each_invested_gate_aborts_on_first_rebalance_without_file(monkeypatch, tmp_path, capsys, side, value):
    frames = _panel(400, n_syms=50)
    monkeypatch.setattr(mr, "read_universe", lambda _: ([], list(frames[0].columns)))
    monkeypatch.setattr(mr, "load_frames", lambda *_: (*frames, []))
    monkeypatch.setattr(mr, "_ir", lambda _: pytest.fail("return statistic before gate"))
    original = mr.simulate_rebalanced
    calls = []

    def simulate(*args, **kwargs):
        current = "basket" if not calls else "benchmark"
        calls.append(current)
        check = kwargs["check_rebalance"]
        if current == side:
            kwargs["check_rebalance"] = lambda row: check({**row, "invested_fraction": value})
        return original(*args, **kwargs)

    monkeypatch.setattr(mr, "simulate_rebalanced", simulate)
    out = tmp_path / "result.json"
    assert mr.main(["--out", str(out)]) == 3
    assert not out.exists()
    err = capsys.readouterr().err
    assert f"{side} invested fraction" in err and str(value) in err
    assert '"first_rebalance": "2018-12-31"' in err


def test_eligible_gate_after_start_aborts_without_file_or_return_statistics(monkeypatch, tmp_path, capsys):
    c, o, v = _panel(400, n_syms=50)
    c.iloc[280, 0] = np.nan
    monkeypatch.setattr(mr, "read_universe", lambda _: ([], list(c.columns)))
    monkeypatch.setattr(mr, "load_frames", lambda *_: (c, o, v, []))
    monkeypatch.setattr(mr, "_ir", lambda _: pytest.fail("return statistic before gate"))
    out = tmp_path / "result.json"
    assert mr.main(["--out", str(out)]) == 3
    assert not out.exists()
    assert "eligible count at 2019-01-31: 49 < 50" in capsys.readouterr().err


def test_existing_result_is_never_overwritten_or_loaded(monkeypatch, tmp_path):
    out = tmp_path / "result.json"
    out.write_text("existing")
    monkeypatch.setattr(mr, "load_frames", lambda *_: pytest.fail("must refuse before loading"))
    assert mr.main(["--out", str(out)]) == 2
    assert out.read_text() == "existing"
