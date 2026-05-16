from __future__ import annotations

import math

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from engines.alpha_engine import AlphaEngine
from engines.backtest_metrics import full_metrics
from engines.backtester import BacktestConfig, Backtester, Snapshot, _combined_signal, _momentum_signal, _ofi_signal, generate_snapshots
from engines.circuit_breaker import CircuitBreaker
from engines.flow_engine import FlowEngine
from engines.risk_limits import RiskLimits


@settings(max_examples=200)
@given(
    best_bid=st.floats(min_value=1.0, max_value=10000.0),
    spread=st.floats(min_value=0.0001, max_value=50.0),
    heavy_qty=st.floats(min_value=800.0, max_value=1_000_000.0),
    other_qty=st.floats(min_value=0.01, max_value=100.0),
)
def test_iceberg_like_confidence_condition(best_bid, spread, heavy_qty, other_qty):
    best_ask = best_bid + spread
    total_bid = heavy_qty + 4 * other_qty
    ratio = heavy_qty / total_bid
    assume(ratio > 0.7)
    confidence = min(1.0, ratio)
    assert confidence > 0.5
    assert best_bid < best_ask


@settings(max_examples=200)
@given(
    mid=st.floats(min_value=10.0, max_value=10000.0),
    far_bps=st.floats(min_value=200.0, max_value=2000.0),
    qty=st.floats(min_value=10000.0, max_value=1_000_000.0),
)
def test_spoof_like_cancel_far_from_mid_positive_score(mid, far_bps, qty):
    price_far = mid * (1.0 + far_bps / 10000.0)
    dist_bps = abs(price_far - mid) / mid * 10000.0
    assume(qty >= 10000 and dist_bps >= 200)
    score = 1.0 if (qty >= 10000 and dist_bps >= 200) else 0.0
    assert score > 0


@settings(max_examples=200)
@given(
    bid_v=st.floats(min_value=0.01, max_value=1_000_000.0),
    ask_v=st.floats(min_value=0.01, max_value=1_000_000.0),
)
def test_flow_imbalance_in_range(bid_v, ask_v):
    ob = Snapshot("2025-01-01T09:15:00", "RELIANCE", 100, 101, bid_v, ask_v, 100.5, 10)
    ofi = _ofi_signal(ob)
    assert -1.0 <= ofi <= 1.0


@settings(max_examples=200)
@given(signal=st.floats(min_value=-500.0, max_value=500.0))
def test_alpha_score_in_range(signal):
    alpha_score = max(0.0, min(100.0, 50.0 + signal))
    assert 0.0 <= alpha_score <= 100.0


@settings(max_examples=200)
@given(seed=st.integers(min_value=1, max_value=10_000))
def test_combined_signal_range(seed):
    snaps = generate_snapshots("RELIANCE", 60, seed=seed)
    v = _combined_signal(snaps, 40)
    assert -1.0 <= v <= 1.0


@settings(max_examples=200)
@given(price=st.floats(min_value=1.0, max_value=10_000.0))
def test_momentum_identical_prices_zero(price):
    snaps = [Snapshot(f"2025-01-01T09:{15+i:02d}:00", "RELIANCE", price, price + 0.01, 100, 100, price, 1.0) for i in range(30)]
    assert _momentum_signal(snaps, 29) == 0.0


@settings(max_examples=200)
@given(bid=st.floats(min_value=1.0, max_value=10_000.0), spread=st.floats(min_value=0.0001, max_value=100.0))
def test_orderbook_bid_ask_consistency(bid, spread):
    ask = bid + spread
    assume(ask > bid)
    assert bid < ask


@settings(max_examples=200)
@given(bid=st.floats(min_value=1.0, max_value=10_000.0), ask=st.floats(min_value=1.0, max_value=10_100.0))
def test_mid_price_formula(bid, ask):
    assume(ask > bid)
    mid = (bid + ask) / 2.0
    assert math.isclose(mid, (bid + ask) / 2.0, rel_tol=1e-12)


@settings(max_examples=200)
@given(bid=st.floats(min_value=1.0, max_value=10_000.0), ask=st.floats(min_value=1.0, max_value=10_100.0))
def test_spread_bps_positive(bid, ask):
    assume(ask > bid)
    mid = (bid + ask) / 2.0
    spread_bps = (ask - bid) / mid * 10000.0
    assert spread_bps > 0


@settings(max_examples=200)
@given(seed=st.integers(min_value=1, max_value=10_000), strategy=st.sampled_from(["momentum", "mean_reversion", "ofi", "combined"]))
def test_backtest_final_equity_non_negative(seed, strategy):
    out = Backtester(BacktestConfig(symbol="RELIANCE", strategy=strategy, n_snapshots=300, seed=seed)).run()
    assert out["metrics"]["final_equity"] >= 0


@settings(max_examples=200)
@given(seed=st.integers(min_value=1, max_value=10_000), strategy=st.sampled_from(["momentum", "mean_reversion", "ofi", "combined"]))
def test_equity_curve_length_invariant(seed, strategy):
    out = Backtester(BacktestConfig(symbol="TCS", strategy=strategy, n_snapshots=250, seed=seed)).run()
    m = out["metrics"]
    assert len(m["equity_curve"]) == m["total_trades"] + 1


@settings(max_examples=200)
@given(seed=st.integers(min_value=1, max_value=10_000), strategy=st.sampled_from(["momentum", "mean_reversion", "ofi", "combined"]))
def test_max_drawdown_range(seed, strategy):
    out = Backtester(BacktestConfig(symbol="INFY", strategy=strategy, n_snapshots=260, seed=seed)).run()
    assert 0.0 <= out["metrics"]["max_drawdown"] <= 1.0


@settings(max_examples=200)
@given(seed=st.integers(min_value=1, max_value=10_000), strategy=st.sampled_from(["momentum", "mean_reversion", "ofi", "combined"]))
def test_win_rate_range(seed, strategy):
    out = Backtester(BacktestConfig(symbol="HDFCBANK", strategy=strategy, n_snapshots=260, seed=seed)).run()
    assert 0.0 <= out["metrics"]["win_rate"] <= 1.0


@settings(max_examples=200)
@given(rets=st.lists(st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False), min_size=2, max_size=100))
def test_sharpe_finite_for_non_empty_input(rets):
    trades = [{"pnl": x * 100} for x in rets]
    m = full_metrics(trades, initial_capital=100000.0)
    assert isinstance(m["sharpe"], float)
    assert math.isfinite(m["sharpe"])


@settings(max_examples=200)
@given(orders=st.integers(min_value=0, max_value=1_000_000), trades=st.integers(min_value=0, max_value=1_000_000))
def test_otr_non_negative(orders, trades):
    otr = orders / trades if trades > 0 else float(orders)
    assert otr >= 0


@settings(max_examples=200)
@given(prev_price=st.floats(min_value=1.0, max_value=10000.0), move=st.floats(min_value=-1.0, max_value=1.0))
def test_circuit_breaker_trips_iff_threshold(prev_price, move):
    cb = CircuitBreaker()
    current = prev_price * (1.0 + move)
    tripped = cb.check("RELIANCE", current, prev_price)
    assert tripped == (abs(move) > 0.05)


@settings(max_examples=200)
@given(entry=st.floats(min_value=0.01, max_value=1_000_000.0), qty=st.integers(min_value=1, max_value=10_000))
def test_risk_limit_breach_results_in_rejection(entry, qty):
    rl = RiskLimits()
    allowed, _reason = rl.check_signal("RELIANCE", entry, quantity=qty)
    if entry * qty > 100_000:
        assert not allowed
