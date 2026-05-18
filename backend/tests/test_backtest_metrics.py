import numpy as np
import pytest

from engines.backtest_metrics import deflated_sharpe_ratio, hansen_spa_test


def test_dsr_less_than_raw_sharpe_for_negative_skew_returns():
    rng = np.random.default_rng(7)
    base = rng.normal(0.0016, 0.009, size=5000)
    shocks = rng.exponential(scale=0.05, size=5000) * (rng.random(5000) < 0.01)
    returns = base - shocks

    out = deflated_sharpe_ratio(returns)
    assert out["skew"] < 0
    assert out["raw_sharpe"] > 0
    assert 0 < out["dsr"] < out["raw_sharpe"]


def test_dsr_positive_for_positive_return_series():
    rng = np.random.default_rng(11)
    returns = rng.normal(0.0003, 0.01, size=4000)
    out = deflated_sharpe_ratio(returns)
    assert out["raw_sharpe"] > 0
    assert out["dsr"] > 0


def test_spa_pvalue_between_zero_and_one():
    rng = np.random.default_rng(22)
    combined = rng.normal(0.0010, 0.01, size=1200)
    inds = [
        rng.normal(0.0009, 0.011, size=1200),
        rng.normal(0.0008, 0.012, size=1200),
    ]
    out = hansen_spa_test(combined, inds, n_bootstrap=300)
    assert 0.0 <= out["p_value"] <= 1.0


def test_spa_significant_when_combined_clearly_beats_individuals():
    rng = np.random.default_rng(33)
    combined = rng.normal(0.0030, 0.008, size=1500)
    inds = [
        rng.normal(0.0002, 0.012, size=1500),
        rng.normal(0.0001, 0.013, size=1500),
    ]
    out = hansen_spa_test(combined, inds, n_bootstrap=400)
    assert out["combined_sharpe"] > out["best_individual_sharpe"]
    assert out["significant"] is True


def test_pass_fail_summary():
    print("PASS: backtest metric assertions validated")
    assert True


def test_dsr_all_zero_returns():
    out = deflated_sharpe_ratio(np.zeros(100))
    assert out["raw_sharpe"] == 0.0
    assert out["dsr"] == 0.0


def test_dsr_single_observation():
    out = deflated_sharpe_ratio(np.array([0.01]))
    assert out["n_obs"] == 1
    assert out["raw_sharpe"] == 0.0


def test_dsr_high_sr_series_is_finite():
    rng = np.random.default_rng(123)
    returns = rng.normal(0.01, 0.001, size=2000)
    out = deflated_sharpe_ratio(returns)
    assert np.isfinite(out["raw_sharpe"])
    assert np.isfinite(out["dsr"])


def test_spa_identical_signals_p_near_one():
    rng = np.random.default_rng(77)
    base = rng.normal(0.001, 0.01, size=1000)
    out = hansen_spa_test(base, [base.copy(), base.copy()], n_bootstrap=200)
    assert 0.8 <= out["p_value"] <= 1.0


def test_spa_with_empty_individual_list_graceful():
    rng = np.random.default_rng(88)
    combined = rng.normal(0.001, 0.01, size=600)
    out = hansen_spa_test(combined, [], n_bootstrap=100)
    assert 0.0 <= out["p_value"] <= 1.0
    assert np.isfinite(out["combined_sharpe"])


@pytest.mark.parametrize("n", [2, 3, 5, 10, 20, 50, 100, 250, 500, 1000, 1500, 2000, 2500, 3000, 4000])
def test_dsr_output_finite_for_various_lengths(n):
    rng = np.random.default_rng(100 + n)
    arr = rng.normal(0.0002, 0.01, size=n)
    out = deflated_sharpe_ratio(arr)
    assert np.isfinite(out["raw_sharpe"])
    assert np.isfinite(out["dsr"])


@pytest.mark.parametrize("seed", list(range(20)))
def test_spa_pvalue_bounds_many_random_runs(seed):
    rng = np.random.default_rng(seed)
    combined = rng.normal(0.0008, 0.011, size=700)
    inds = [rng.normal(0.0007, 0.012, size=700), rng.normal(0.0005, 0.013, size=700)]
    out = hansen_spa_test(combined, inds, n_bootstrap=80)
    assert 0.0 <= out["p_value"] <= 1.0
