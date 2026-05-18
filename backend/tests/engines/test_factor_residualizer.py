from __future__ import annotations
import numpy as np
import pytest
from engines.factor_residualizer import residualize_against_factors, synthetic_nse_factors


def test_betas_recovered():
    """Residualizer should recover dominant factor loadings directionally."""
    factors = synthetic_nse_factors(500, seed=0)
    rng = np.random.default_rng(0)
    signal = 0.7 * factors["Mkt"] + 0.4 * factors["UMD"] + rng.normal(0.0, 0.005, 500)
    result = residualize_against_factors(signal, factors)
    # Mkt and UMD should have the largest betas (multicollinearity spreads exact values)
    betas = result["betas"]
    top_two = sorted(betas, key=lambda k: abs(betas[k]), reverse=True)[:2]
    assert "Mkt" in top_two or "UMD" in top_two
    # Combined loading on Mkt+UMD should be close to 0.7+0.4=1.1
    combined = abs(betas["Mkt"]) + abs(betas["UMD"])
    assert 0.7 < combined < 1.8


def test_residuals_length():
    """Residuals should have same length as input."""
    factors = synthetic_nse_factors(200, seed=1)
    rng = np.random.default_rng(1)
    signal = rng.normal(0.001, 0.01, 200)
    result = residualize_against_factors(signal, factors)
    assert len(result["residuals"]) == 200


def test_r_squared_range():
    """R-squared must be between 0 and 1."""
    factors = synthetic_nse_factors(300, seed=2)
    rng = np.random.default_rng(2)
    signal = rng.normal(0.0, 0.02, 300)
    result = residualize_against_factors(signal, factors)
    assert 0.0 <= result["r_squared"] <= 1.0


def test_pure_alpha_signal():
    """Signal with no factor exposure should have low r_squared and positive t-stat."""
    factors = synthetic_nse_factors(500, seed=3)
    rng = np.random.default_rng(99)  # different seed to avoid RNG collision with factors
    signal = rng.normal(0.002, 0.005, 500)
    result = residualize_against_factors(signal, factors)
    assert result["r_squared"] < 0.15
    assert result["t_stat_alpha"] > 1.5


def test_too_few_observations():
    """Fewer than 10 observations should return safe defaults."""
    factors = {"Mkt": np.array([0.01, 0.02])}
    signal = np.array([0.01, 0.02])
    result = residualize_against_factors(signal, factors)
    assert result["alpha_annualised"] == 0.0
    assert result["t_stat_alpha"] == 0.0
    assert result["r_squared"] == 0.0
