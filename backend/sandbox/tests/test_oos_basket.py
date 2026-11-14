from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import oos_basket
from basket_backtest import monthly_rebalance_dates, simulate
from prices import point_in_time_adv


def _panel(n_days: int = 800, n_syms: int = 40, winners: int = 0, seed: int = 11):
    """Synthetic daily panel. The first `winners` names have a positive daily drift."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2012-01-02", periods=n_days)
    syms = [f"W{i:02d}" if i < winners else f"L{i:02d}" for i in range(n_syms)]
    drift = np.array([0.002 if s.startswith("W") else -0.0005 for s in syms])
    rets = rng.normal(drift, 0.01, size=(n_days, n_syms))
    closes = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=dates, columns=syms)
    opens = closes * (1 + rng.normal(0, 0.002, size=closes.shape))
    volumes = pd.DataFrame(rng.integers(50_000, 500_000, size=closes.shape).astype(float),
                           index=dates, columns=syms)
    return closes, opens, volumes


def test_identical_basket_and_benchmark_give_zero_active_returns():
    closes, opens, volumes = _panel(winners=10)
    res = oos_basket.run_arm(closes, opens, volumes, basket_k=len(closes.columns))
    assert res["n_months"] > 20
    assert all(m["active"] == 0.0 for m in res["monthly"])
    assert res["ir"] == 0.0
    assert res["ci_lower"] == 0.0 and res["ci_upper"] == 0.0
    assert res["outcome"] == "Inconclusive"


def test_planted_winners_give_positive_ir():
    closes, opens, volumes = _panel(winners=10)
    res = oos_basket.run_arm(closes, opens, volumes)
    assert res["ir"] > 0.0
    assert sum(m["active"] > 0 for m in res["monthly"]) > res["n_months"] / 2


def test_run_is_deterministic_with_fixed_seed():
    closes, opens, volumes = _panel(winners=10)
    a = oos_basket.run_arm(closes, opens, volumes)
    b = oos_basket.run_arm(closes, opens, volumes)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_bootstrap_point_matches_protocol_ir():
    closes, opens, volumes = _panel(winners=10)
    res = oos_basket.run_arm(closes, opens, volumes)
    active = np.asarray([m["active"] for m in res["monthly"]])
    assert res["ir"] == pytest.approx(float(active.mean() / active.std() * np.sqrt(12)), rel=1e-12)


def test_only_names_with_full_adv_window_are_ever_held():
    closes, opens, volumes = _panel(winners=10)
    closes.iloc[:300, closes.columns.get_loc("L39")] = np.nan  # late listing
    volumes.iloc[:300, volumes.columns.get_loc("L39")] = np.nan
    sched = monthly_rebalance_dates(closes, closes.index.max().date(), months_back=40)
    adv = point_in_time_adv(closes, volumes, sched)
    res = simulate(closes, {}, opens, sched, adv_by_date=adv)
    for rb, basket, _ in res["baskets"]:
        assert set(basket) <= set(adv[rb]), rb


def test_loader_refuses_hash_mismatch(tmp_path: Path):
    closes, opens, volumes = _panel(n_days=120, n_syms=2, winners=1)
    import hashlib
    manifest = {"unavailable": {"NOPE": {"reason": "no data"}}, "files": {}}
    for sym in closes.columns:
        df = pd.DataFrame({"Close": closes[sym], "High": closes[sym], "Low": closes[sym],
                           "Open": opens[sym], "Volume": volumes[sym]})
        df.index.name = "Date"
        path = tmp_path / f"{sym}.csv"
        df.to_csv(path)
        manifest["files"][path.name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (tmp_path / "MANIFEST.json").write_text(json.dumps(manifest))

    loaded_c, _, _, unavail = oos_basket.load_snapshot(tmp_path, ["W00", "L01", "NOPE"])
    assert list(loaded_c.columns) == ["W00", "L01"] and "NOPE" in unavail

    tampered = pd.read_csv(tmp_path / "W00.csv", index_col=0, parse_dates=True)
    tampered["Close"] = tampered["Close"] + 1.0
    tampered.to_csv(tmp_path / "W00.csv")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        oos_basket.load_snapshot(tmp_path, ["W00", "L01"])


def test_corrected_identical_basket_and_benchmark_give_zero_active_returns():
    closes, opens, volumes = _panel(winners=10)
    res = oos_basket.run_corrected_arm(closes, opens, volumes, basket_k=len(closes.columns))
    assert res["n_months"] > 20
    assert all(m["active"] == 0.0 for m in res["monthly"])
    assert res["ir"] == 0.0
    assert res["outcome"] == "no evidence of an edge"


def test_corrected_run_is_deterministic_and_fully_invested():
    closes, opens, volumes = _panel(winners=10)
    a = oos_basket.run_corrected_arm(closes, opens, volumes)
    b = oos_basket.run_corrected_arm(closes, opens, volumes)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    for side in ("basket", "benchmark"):
        for row in a["exposure"][f"{side}_rebalances"]:
            assert 0.99 <= row["invested_fraction"] <= 1.0


def test_amendment_outcome_wording_never_says_pass():
    assert oos_basket.amendment_outcome(-1.0, -0.1) == "not supported, also after correction"
    assert oos_basket.amendment_outcome(-0.5, 0.5) == "no evidence of an edge"
    assert oos_basket.amendment_outcome(0.1, 1.0) == "candidate only"
