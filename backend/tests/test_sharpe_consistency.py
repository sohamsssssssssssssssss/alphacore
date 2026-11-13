import numpy as np
import pytest
from engines.backtest_metrics import compute_sharpe, stationary_bootstrap_sharpe_ci

RETURNS = [.012, -.008, .025, -.017, .006, .019, -.004, .031, -.013, .008]
KWARGS = dict(n_bootstrap=100, mean_block_length=3, periods_per_year=12, seed=17)


def test_v1_default_is_bit_identical():
    # Captured from the unmodified v1 implementation, before introducing risk_free.
    expected = {'sharpe': '0x1.531672c95ccf6p+0', 'ci_lower': '0x1.d2f0fddbce23ep-4',
                'ci_upper': '0x1.51d6f75414917p+1', 'ci_width': '0x1.433f6f6536205p+1'}
    result = stationary_bootstrap_sharpe_ci(RETURNS, **KWARGS)
    assert {key: result[key].hex() for key in expected} == expected
    assert result == stationary_bootstrap_sharpe_ci(RETURNS, risk_free=0, **KWARGS)


def test_matching_rf_point_is_inside_full_bootstrap_range():
    result = stationary_bootstrap_sharpe_ci(RETURNS, risk_free=.065, confidence=1, **KWARGS)
    point = compute_sharpe(RETURNS, periods_per_year=12, risk_free=.065)
    assert result['sharpe'] == pytest.approx(point, rel=1e-14)
    assert result['ci_lower'] <= point <= result['ci_upper']


def test_positive_rf_shifts_each_bootstrap_quantile_down():
    zero = stationary_bootstrap_sharpe_ci(RETURNS, **KWARGS)
    excess = stationary_bootstrap_sharpe_ci(RETURNS, risk_free=.065, **KWARGS)
    assert excess['sharpe'] < zero['sharpe']
    assert excess['ci_lower'] < zero['ci_lower']
    assert excess['ci_upper'] < zero['ci_upper']
    rf_period = 1.065 ** (1 / 12) - 1
    expected_shift = rf_period / np.std(RETURNS) * np.sqrt(12)
    assert zero['sharpe'] - excess['sharpe'] == pytest.approx(expected_shift)
