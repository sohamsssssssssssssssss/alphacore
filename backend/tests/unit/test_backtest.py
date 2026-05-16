from __future__ import annotations

import pytest

from engines.backtest_metrics import (
    build_equity_curve,
    compute_calmar,
    compute_max_drawdown,
    compute_pnl,
    compute_returns_from_equity,
    compute_sharpe,
    compute_win_rate,
    full_metrics,
)
from engines.backtester import (
    STRATEGIES,
    BacktestConfig,
    Backtester,
    Snapshot,
    _combined_signal,
    _get_direction,
    _mean_reversion_signal,
    _momentum_signal,
    _ofi_signal,
    generate_snapshots,
    run_strategy_comparison,
)


def _trade(pnl: float) -> dict:
    return {"pnl": float(pnl)}


# METRICS

def test_compute_pnl_empty_list():
    assert compute_pnl([]) == 0.0


def test_compute_pnl_single_winning_trade():
    assert compute_pnl([_trade(120.5)]) == pytest.approx(120.5)


def test_compute_pnl_mixed_wins_losses():
    assert compute_pnl([_trade(10), _trade(-3), _trade(2.5)]) == pytest.approx(9.5)


def test_compute_returns_from_equity_empty():
    assert compute_returns_from_equity([]) == []


def test_compute_returns_from_equity_single_value():
    assert compute_returns_from_equity([100000.0]) == []


def test_compute_returns_from_equity_known_values():
    rets = compute_returns_from_equity([100, 110, 99])
    assert rets[0] == pytest.approx(0.10)
    assert rets[1] == pytest.approx(-0.10)


def test_build_equity_curve_no_trades():
    assert build_equity_curve(1000.0, []) == [1000.0]


def test_build_equity_curve_cumulative():
    curve = build_equity_curve(1000.0, [_trade(10), _trade(-5), _trade(2)])
    assert curve == [1000.0, 1010.0, 1005.0, 1007.0]


def test_compute_sharpe_empty_returns():
    assert compute_sharpe([]) == 0.0


def test_compute_sharpe_constant_returns_std_zero():
    assert compute_sharpe([0.01, 0.01, 0.01]) == 0.0


def test_compute_sharpe_positive_returns_positive_sharpe():
    assert compute_sharpe([0.03, 0.02, 0.025, 0.018]) > 0


def test_compute_max_drawdown_monotone_rising():
    assert compute_max_drawdown([100, 101, 102, 110]) == 0.0


def test_compute_max_drawdown_known_fraction():
    dd = compute_max_drawdown([100, 120, 90, 95])
    assert dd == pytest.approx((120 - 90) / 120)


def test_compute_win_rate_all_wins():
    out = compute_win_rate([_trade(1), _trade(2), _trade(3)])
    assert out["win_rate"] == 1.0
    assert out["wins"] == 3
    assert out["losses"] == 0


def test_compute_win_rate_all_losses():
    out = compute_win_rate([_trade(-1), _trade(-2)])
    assert out["win_rate"] == 0.0
    assert out["wins"] == 0
    assert out["losses"] == 2


def test_compute_win_rate_mixed_values():
    out = compute_win_rate([_trade(4), _trade(-2), _trade(2), _trade(-2)])
    assert out["win_rate"] == pytest.approx(0.5)
    assert out["profit_factor"] == pytest.approx(1.5)


def test_compute_calmar_zero_max_drawdown():
    assert compute_calmar(1000, 100000, 0.0) == 0.0


def test_compute_calmar_known_values():
    assert compute_calmar(1000, 100000, 0.1) == pytest.approx(0.1)


def test_full_metrics_empty_trades_fields():
    out = full_metrics([], initial_capital=50000.0)
    assert out["total_pnl"] == 0.0
    assert out["total_trades"] == 0
    assert out["equity_curve"] == [50000.0]


def test_full_metrics_known_trades_fields_and_types():
    out = full_metrics([_trade(100), _trade(-20)], initial_capital=1000.0)
    for key in [
        "total_pnl", "sharpe", "max_drawdown", "win_rate", "profit_factor", "wins", "losses",
        "calmar", "total_trades", "final_equity", "equity_curve", "pnl_series",
    ]:
        assert key in out
    assert isinstance(out["equity_curve"], list)
    assert isinstance(out["pnl_series"], list)


# SNAPSHOT GENERATOR

def test_generate_snapshots_exact_count():
    snaps = generate_snapshots("RELIANCE", 77, seed=1)
    assert len(snaps) == 77


def test_generate_snapshots_reproducibility_same_seed():
    a = generate_snapshots("TCS", 25, seed=42)
    b = generate_snapshots("TCS", 25, seed=42)
    assert [x.mid_price for x in a] == [x.mid_price for x in b]


def test_generate_snapshots_different_seed_different_prices():
    a = generate_snapshots("INFY", 25, seed=10)
    b = generate_snapshots("INFY", 25, seed=11)
    assert [x.mid_price for x in a] != [x.mid_price for x in b]


def test_generate_snapshots_bid_less_than_ask_always():
    snaps = generate_snapshots("HDFCBANK", 120, seed=5)
    assert all(s.bid_price < s.ask_price for s in snaps)


def test_generate_snapshots_spread_clamped_range():
    snaps = generate_snapshots("ICICIBANK", 120, seed=5)
    assert all(1.0 <= s.spread_bps <= 20.0 for s in snaps)


def test_generate_snapshots_timestamps_monotonic():
    snaps = generate_snapshots("RELIANCE", 50, seed=5)
    assert all(snaps[i].timestamp < snaps[i + 1].timestamp for i in range(len(snaps) - 1))


# SIGNALS

def test_momentum_signal_idx_zero_returns_zero():
    snaps = generate_snapshots("RELIANCE", 20, seed=2)
    assert _momentum_signal(snaps, 0) == 0.0


def test_momentum_signal_enough_history_float():
    snaps = generate_snapshots("RELIANCE", 40, seed=2)
    assert isinstance(_momentum_signal(snaps, 20), float)


def test_mean_reversion_signal_idx_zero_returns_zero():
    snaps = generate_snapshots("RELIANCE", 20, seed=2)
    assert _mean_reversion_signal(snaps, 0) == 0.0


def test_mean_reversion_signal_constant_prices_zero():
    snaps = [Snapshot("2025-01-01T09:15:00", "RELIANCE", 100, 101, 10, 10, 100.5, 10) for _ in range(25)]
    assert _mean_reversion_signal(snaps, 24) == 0.0


def test_ofi_signal_bid_much_greater_than_ask():
    s = Snapshot("2025-01-01T09:15:00", "RELIANCE", 100, 101, 1000, 1, 100.5, 10)
    assert _ofi_signal(s) > 0.95


def test_ofi_signal_equal_volumes_zero():
    s = Snapshot("2025-01-01T09:15:00", "RELIANCE", 100, 101, 100, 100, 100.5, 10)
    assert _ofi_signal(s) == 0.0


def test_combined_signal_range_minus1_to_plus1():
    snaps = generate_snapshots("RELIANCE", 60, seed=7)
    v = _combined_signal(snaps, 40)
    assert -1.0 <= v <= 1.0


# DIRECTION

def test_get_direction_momentum_cases():
    assert _get_direction(5.0, "momentum") == "LONG"
    assert _get_direction(-5.0, "momentum") == "SHORT"
    assert _get_direction(0.0, "momentum") is None


def test_get_direction_mean_reversion_inverted():
    assert _get_direction(-2.0, "mean_reversion") == "LONG"
    assert _get_direction(2.0, "mean_reversion") == "SHORT"


def test_get_direction_ofi_cases():
    assert _get_direction(0.5, "ofi") == "LONG"
    assert _get_direction(-0.5, "ofi") == "SHORT"


def test_get_direction_combined_long_case():
    assert _get_direction(0.2, "combined") == "LONG"


# END TO END

@pytest.mark.parametrize("strategy", STRATEGIES)
def test_backtester_run_all_strategies_returns_shape(strategy: str):
    cfg = BacktestConfig(symbol="RELIANCE", strategy=strategy, n_snapshots=200)
    out = Backtester(cfg).run()
    assert set(out.keys()) == {"config", "metrics", "trades"}


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_backtester_metrics_contains_required_fields(strategy: str):
    cfg = BacktestConfig(symbol="RELIANCE", strategy=strategy, n_snapshots=200)
    out = Backtester(cfg).run()
    m = out["metrics"]
    for k in [
        "total_pnl", "sharpe", "max_drawdown", "win_rate", "profit_factor", "wins", "losses",
        "calmar", "total_trades", "final_equity", "equity_curve", "pnl_series",
    ]:
        assert k in m


def test_backtester_equity_curve_length_consistency():
    out = Backtester(BacktestConfig(symbol="RELIANCE", strategy="combined", n_snapshots=250)).run()
    m = out["metrics"]
    assert len(m["equity_curve"]) == m["total_trades"] + 1


def test_backtester_final_equity_non_negative():
    out = Backtester(BacktestConfig(symbol="RELIANCE", strategy="combined", n_snapshots=250)).run()
    assert out["metrics"]["final_equity"] >= 0.0


def test_run_strategy_comparison_leaderboard_length_four():
    out = run_strategy_comparison(symbol="TCS", n_snapshots=200)
    assert len(out["leaderboard"]) == 4


def test_run_strategy_comparison_sorted_by_sharpe_desc():
    out = run_strategy_comparison(symbol="TCS", n_snapshots=200)
    sharpes = [row["sharpe"] for row in out["leaderboard"]]
    assert sharpes == sorted(sharpes, reverse=True)


def test_run_strategy_comparison_entry_fields_present():
    out = run_strategy_comparison(symbol="TCS", n_snapshots=200)
    row = out["leaderboard"][0]
    for k in ["rank", "strategy", "sharpe", "total_pnl", "win_rate", "max_drawdown", "total_trades", "calmar"]:
        assert k in row


def test_run_strategy_comparison_details_all_keys_present():
    out = run_strategy_comparison(symbol="TCS", n_snapshots=200)
    assert set(out["details"].keys()) == {"momentum", "mean_reversion", "ofi", "combined"}
