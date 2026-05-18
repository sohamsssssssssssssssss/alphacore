from __future__ import annotations

import math

import numpy as np
from scipy import stats


def compute_pnl(trades: list[dict]) -> float:
    if not trades:
        return 0.0
    return float(sum(float(t.get("pnl", 0.0)) for t in trades))


def compute_returns_from_equity(equity_curve: list[float]) -> list[float]:
    if len(equity_curve) < 2:
        return []
    returns: list[float] = []
    for i in range(1, len(equity_curve)):
        prev = float(equity_curve[i - 1])
        cur = float(equity_curve[i])
        if prev == 0:
            returns.append(0.0)
        else:
            returns.append((cur - prev) / prev)
    return returns


def build_equity_curve(initial_capital: float, trades: list[dict]) -> list[float]:
    curve = [float(initial_capital)]
    capital = float(initial_capital)
    for trade in trades:
        capital += float(trade.get("pnl", 0.0))
        curve.append(float(capital))
    return curve


def compute_sharpe(returns: list[float], periods_per_year: int = 252, risk_free: float = 0.065) -> float:
    if len(returns) < 2:
        return 0.0

    rf_per_period = (1.0 + risk_free) ** (1.0 / periods_per_year) - 1.0
    excess = [float(r) - rf_per_period for r in returns]
    mean_excess = sum(excess) / len(excess)
    var = sum((x - mean_excess) ** 2 for x in excess) / len(excess)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return float((mean_excess / std) * math.sqrt(periods_per_year))


def compute_max_drawdown(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0

    peak = float(equity_curve[0])
    max_dd = 0.0
    for v in equity_curve:
        cur = float(v)
        if cur > peak:
            peak = cur
        if peak > 0:
            dd = (peak - cur) / peak
            if dd > max_dd:
                max_dd = dd
    return float(max_dd)


def compute_win_rate(trades: list[dict]) -> dict:
    if not trades:
        return {"win_rate": 0.0, "profit_factor": 0.0, "wins": 0, "losses": 0}

    pnls = [float(t.get("pnl", 0.0)) for t in trades]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]

    wins_count = len(wins)
    losses_count = len(losses)
    win_rate = wins_count / len(pnls) if pnls else 0.0

    sum_wins = sum(wins)
    sum_losses_abs = abs(sum(losses))
    profit_factor = (sum_wins / sum_losses_abs) if sum_losses_abs > 0 else 0.0

    return {
        "win_rate": float(win_rate),
        "profit_factor": float(profit_factor),
        "wins": int(wins_count),
        "losses": int(losses_count),
    }


def compute_calmar(total_pnl: float, initial_capital: float, max_drawdown: float) -> float:
    if max_drawdown == 0 or initial_capital == 0:
        return 0.0
    return float((total_pnl / initial_capital) / max_drawdown)


def full_metrics(trades: list[dict], initial_capital: float = 100000.0, periods_per_year: int = 252) -> dict:
    total_pnl = compute_pnl(trades)
    equity_curve = build_equity_curve(initial_capital, trades)
    returns = compute_returns_from_equity(equity_curve)
    sharpe = compute_sharpe(returns, periods_per_year=periods_per_year)
    max_drawdown = compute_max_drawdown(equity_curve)
    wr = compute_win_rate(trades)
    calmar = compute_calmar(total_pnl, initial_capital, max_drawdown)
    pnl_series = [float(t.get("pnl", 0.0)) for t in trades]

    return {
        "total_pnl": float(total_pnl),
        "sharpe": float(sharpe),
        "max_drawdown": float(max_drawdown),
        "win_rate": float(wr["win_rate"]),
        "profit_factor": float(wr["profit_factor"]),
        "wins": int(wr["wins"]),
        "losses": int(wr["losses"]),
        "calmar": float(calmar),
        "total_trades": int(len(trades)),
        "final_equity": float(equity_curve[-1] if equity_curve else initial_capital),
        "equity_curve": [float(x) for x in equity_curve],
        "pnl_series": [float(x) for x in pnl_series],
    }


def deflated_sharpe_ratio(returns, sr_benchmark: float = 0.0) -> dict:
    """
    Compute Deflated Sharpe Ratio (DSR) from a return series.

    DSR penalizes raw Sharpe for non-Gaussian tails/shape. In practice DSR tends to be
    below raw Sharpe when returns are negatively skewed (left-tail risk) and/or show
    positive excess kurtosis (fat tails), because those effects reduce confidence that
    observed Sharpe reflects stable skill rather than luck.
    """
    arr = np.asarray(returns, dtype=float)
    n_obs = int(arr.size)
    if n_obs < 2:
        return {
            "raw_sharpe": 0.0,
            "dsr": 0.0,
            "skew": 0.0,
            "kurt": 0.0,
            "n_obs": n_obs,
            "sr_benchmark": float(sr_benchmark),
        }

    std = float(np.std(arr))
    if std == 0.0:
        raw_sharpe = 0.0
    else:
        raw_sharpe = float(np.mean(arr) / std * np.sqrt(252.0))

    skew = float(stats.skew(arr, bias=False))
    kurt = float(stats.kurtosis(arr, fisher=True, bias=False))
    if not np.isfinite(skew):
        skew = 0.0
    if not np.isfinite(kurt):
        kurt = 0.0

    denom = float(n_obs - 1)
    term = (1.0 - skew * raw_sharpe + ((kurt - 1.0) / 4.0) * (raw_sharpe**2)) / denom
    term = max(term, 0.0)
    dsr = float(raw_sharpe * np.sqrt(term))

    return {
        "raw_sharpe": float(raw_sharpe),
        "dsr": dsr,
        "skew": skew,
        "kurt": kurt,
        "n_obs": n_obs,
        "sr_benchmark": float(sr_benchmark),
    }


def hansen_spa_test(combined_returns, individual_returns_list, n_bootstrap: int = 1000) -> dict:
    """
    Hansen SPA-style bootstrap test for whether combiner performance exceeds constituents.

    Null hypothesis: combined Sharpe <= best individual Sharpe.
    A p-value < 0.05 means bootstrap evidence suggests rejecting the null, i.e. the
    combiner's Sharpe is statistically better than the best individual signal.
    """
    combined = np.asarray(combined_returns, dtype=float)
    individuals = [np.asarray(x, dtype=float) for x in individual_returns_list]

    if combined.size < 2:
        return {
            "p_value": 1.0,
            "combined_sharpe": 0.0,
            "best_individual_sharpe": 0.0,
            "significant": False,
        }

    def _sharpe(a: np.ndarray) -> float:
        if a.size < 2:
            return 0.0
        s = float(np.std(a))
        if s == 0.0:
            return 0.0
        return float(np.mean(a) / s * np.sqrt(252.0))

    combined_sharpe = _sharpe(combined)
    best_individual_sharpe = max((_sharpe(x) for x in individuals), default=0.0)

    t = combined.size
    rng = np.random.default_rng(42)
    null_holds = 0
    for _ in range(int(n_bootstrap)):
        idx = rng.integers(0, t, size=t)
        c_b = combined[idx]
        ind_b = [x[idx] if x.size >= t else x[rng.integers(0, x.size, size=x.size)] for x in individuals if x.size > 0]
        c_s = _sharpe(c_b)
        b_s = max((_sharpe(x) for x in ind_b), default=0.0)
        if c_s <= b_s:
            null_holds += 1

    p_value = float(null_holds / max(int(n_bootstrap), 1))
    return {
        "p_value": p_value,
        "combined_sharpe": float(combined_sharpe),
        "best_individual_sharpe": float(best_individual_sharpe),
        "significant": bool(p_value < 0.05),
    }


def stationary_bootstrap_sharpe_ci(
    returns,
    n_bootstrap: int = 1000,
    confidence: float = 0.95,
    mean_block_length: int = 10,
    periods_per_year: int = 252,
    seed: int = 42,
) -> dict:
    """
    Politis-Romano stationary bootstrap confidence interval for annualised Sharpe ratio.

    Unlike IID bootstrap, stationary bootstrap draws variable-length blocks so the
    autocorrelation structure of the return series is preserved. Block lengths are
    geometrically distributed with mean = mean_block_length.

    Returns:
        sharpe        - point estimate
        ci_lower      - lower bound of CI
        ci_upper      - upper bound of CI
        ci_width      - ci_upper - ci_lower (narrower = more reliable)
        confidence    - requested confidence level
        n_bootstrap   - number of bootstrap samples used
        n_obs         - number of observations
        reliable      - True if ci_lower > 0 (edge is positive with confidence)
    """
    arr = np.asarray(returns, dtype=float)
    n = arr.size
    if n < 2:
        return {
            "sharpe": 0.0,
            "ci_lower": 0.0,
            "ci_upper": 0.0,
            "ci_width": 0.0,
            "confidence": float(confidence),
            "n_bootstrap": int(n_bootstrap),
            "n_obs": int(n),
            "reliable": False,
        }

    def _sharpe(a: np.ndarray) -> float:
        s = float(np.std(a))
        if s == 0.0:
            return 0.0
        return float(np.mean(a) / s * np.sqrt(float(periods_per_year)))

    point_sharpe = _sharpe(arr)
    p = 1.0 / float(mean_block_length)
    rng = np.random.default_rng(seed)
    bootstrap_sharpes: list[float] = []

    for _ in range(int(n_bootstrap)):
        sample = np.empty(n, dtype=float)
        pos = 0
        start = int(rng.integers(0, n))
        while pos < n:
            block_len = int(np.ceil(rng.geometric(p)))
            block_len = min(block_len, n - pos)
            for j in range(block_len):
                sample[pos] = arr[(start + j) % n]
                pos += 1
            start = int(rng.integers(0, n))
        bootstrap_sharpes.append(_sharpe(sample))

    bs = np.array(bootstrap_sharpes, dtype=float)
    alpha = 1.0 - confidence
    ci_lower = float(np.percentile(bs, 100.0 * alpha / 2.0))
    ci_upper = float(np.percentile(bs, 100.0 * (1.0 - alpha / 2.0)))

    return {
        "sharpe": float(point_sharpe),
        "ci_lower": float(ci_lower),
        "ci_upper": float(ci_upper),
        "ci_width": float(ci_upper - ci_lower),
        "confidence": float(confidence),
        "n_bootstrap": int(n_bootstrap),
        "n_obs": int(n),
        "reliable": bool(ci_lower > 0.0),
    }
