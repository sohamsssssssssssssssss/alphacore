from __future__ import annotations
import numpy as np


def _ols_residuals(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    """Return OLS residuals of y ~ X (X must include intercept column)."""
    coeffs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    return y - X @ coeffs


def residualize_against_factors(
    signal_returns: np.ndarray,
    factor_returns: dict[str, np.ndarray],
) -> dict:
    """
    Regress signal_returns against FF5+UMD factors and return the residuals.

    Factors expected (pass whatever subset you have, minimum = Mkt):
        Mkt  - market excess return
        SMB  - small minus big (size)
        HML  - high minus low (value)
        RMW  - robust minus weak (profitability)
        CMA  - conservative minus aggressive (investment)
        UMD  - up minus down (momentum)

    Returns:
        residuals       - alpha returns unexplained by factors
        betas           - dict of factor loadings
        r_squared       - fraction of variance explained by factors
        alpha_annualised- annualised alpha (residual mean * sqrt(252))
        t_stat_alpha    - t-statistic of the intercept (is alpha real?)
        n_obs           - number of observations used
    """
    y = np.asarray(signal_returns, dtype=float)
    n = y.size

    if n < 10:
        return {
            "residuals": y.tolist(),
            "betas": {},
            "r_squared": 0.0,
            "alpha_annualised": 0.0,
            "t_stat_alpha": 0.0,
            "n_obs": n,
        }

    factor_names = list(factor_returns.keys())
    factor_matrix = np.column_stack([
        np.asarray(factor_returns[f], dtype=float) for f in factor_names
    ])

    # Align lengths
    min_len = min(n, factor_matrix.shape[0])
    y = y[:min_len]
    factor_matrix = factor_matrix[:min_len]

    # Build design matrix with intercept
    X = np.column_stack([np.ones(min_len), factor_matrix])

    coeffs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    residuals = y - X @ coeffs

    # R-squared
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Alpha t-stat
    n_obs = int(min_len)
    k = X.shape[1]
    if n_obs > k:
        s2 = ss_res / (n_obs - k)
        XtX_inv = np.linalg.pinv(X.T @ X)
        se_alpha = float(np.sqrt(s2 * XtX_inv[0, 0]))
        t_stat_alpha = float(coeffs[0] / se_alpha) if se_alpha > 0 else 0.0
    else:
        t_stat_alpha = 0.0

    alpha_annualised = float(coeffs[0] * np.sqrt(252.0))
    betas = {name: float(coeffs[i + 1]) for i, name in enumerate(factor_names)}

    return {
        "residuals": residuals.tolist(),
        "betas": betas,
        "r_squared": float(r_squared),
        "alpha_annualised": float(alpha_annualised),
        "t_stat_alpha": float(t_stat_alpha),
        "n_obs": n_obs,
    }


def synthetic_nse_factors(n: int = 252, seed: int = 42) -> dict[str, np.ndarray]:
    """
    Generate synthetic NSE-like daily factor returns for testing.
    In production replace with real Nifty factor data.
    """
    rng = np.random.default_rng(seed)
    return {
        "Mkt": rng.normal(0.0004, 0.012, n),
        "SMB": rng.normal(0.0001, 0.006, n),
        "HML": rng.normal(0.0001, 0.006, n),
        "RMW": rng.normal(0.0001, 0.005, n),
        "CMA": rng.normal(0.0001, 0.005, n),
        "UMD": rng.normal(0.0002, 0.008, n),
    }
