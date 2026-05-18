from engines.ml.features import OrderBookFeatureEngine
import numpy as np
import pytest


def test_feature_engine_compute_42_features_and_core_properties():
    snapshot = {
        "bid_prices": [99.0, 98.8, 98.6, 98.4, 98.2],
        "bid_qtys": [120, 110, 100, 90, 80],
        "ask_prices": [101.0, 101.2, 101.4, 101.6, 101.8],
        "ask_qtys": [130, 120, 110, 100, 90],
        "last_price": 100.5,
        "volume": 10000,
        "timestamp_ns": 1_700_000_000_000_000_000,
        "iceberg_confidence": 0.73,
        "iceberg_side": "BID",
        "spoof_score": 65.0,
        "spoof_severity": "HIGH",
        "market_returns": [0.001, -0.0005, 0.0008, 0.0002],
    }

    eng = OrderBookFeatureEngine(use_cpp=True)
    out = eng.compute(snapshot)

    assert len(out) == 42

    best_bid = snapshot["bid_prices"][0]
    best_ask = snapshot["ask_prices"][0]
    assert abs(out["mid_price"] - ((best_bid + best_ask) / 2.0)) < 1e-12

    assert -1.0 <= out["depth_imbalance"] <= 1.0
    assert out["iceberg_confidence"] == snapshot["iceberg_confidence"]


def _snapshot(seed: int = 0):
    rng = np.random.default_rng(seed)
    bid0 = 99.0 + rng.normal(0, 0.5)
    ask0 = bid0 + abs(rng.normal(1.0, 0.2))
    return {
        "bid_prices": [bid0 - i * 0.2 for i in range(5)],
        "bid_qtys": [max(1.0, 100 + rng.normal(0, 20)) for _ in range(5)],
        "ask_prices": [ask0 + i * 0.2 for i in range(5)],
        "ask_qtys": [max(1.0, 100 + rng.normal(0, 20)) for _ in range(5)],
        "last_price": (bid0 + ask0) / 2.0,
        "volume": max(1.0, 5000 + rng.normal(0, 500)),
        "timestamp_ns": int(1_700_000_000_000_000_000 + seed),
        "iceberg_confidence": float(rng.uniform(0, 1)),
        "iceberg_side": "BID" if seed % 2 == 0 else "ASK",
        "spoof_score": float(rng.uniform(0, 100)),
        "spoof_severity": "HIGH" if seed % 3 == 0 else "LOW",
        "market_returns": [float(x) for x in rng.normal(0, 0.01, size=10)],
    }


@pytest.mark.parametrize("seed", list(range(30)))
def test_features_all_keys_present_and_finite(seed):
    eng = OrderBookFeatureEngine(use_cpp=False)
    out = eng.compute(_snapshot(seed))
    assert len(out) == 42
    for v in out.values():
        assert np.isfinite(float(v))


@pytest.mark.parametrize("seed", list(range(10)))
def test_spread_features_non_negative(seed):
    eng = OrderBookFeatureEngine(use_cpp=False)
    out = eng.compute(_snapshot(seed))
    assert out["spread_abs"] >= 0.0
    assert out["spread_bps"] >= 0.0
    assert out["roll_spread"] >= 0.0
    assert out["corwin_schultz_spread"] >= 0.0


@pytest.mark.parametrize("seed", list(range(10)))
def test_depth_imbalance_bounded(seed):
    eng = OrderBookFeatureEngine(use_cpp=False)
    out = eng.compute(_snapshot(seed))
    assert -1.0 <= out["depth_imbalance"] <= 1.0


def test_batch_compute_shape():
    eng = OrderBookFeatureEngine(use_cpp=False)
    snaps = [_snapshot(i) for i in range(25)]
    df = eng.compute_batch(snaps)
    assert df.shape == (25, 42)


@pytest.mark.parametrize("seed", list(range(10)))
def test_micro_price_within_best_quotes(seed):
    snap = _snapshot(seed)
    eng = OrderBookFeatureEngine(use_cpp=False)
    out = eng.compute(snap)
    best_bid = snap["bid_prices"][0]
    best_ask = snap["ask_prices"][0]
    assert best_bid <= out["micro_price"] <= best_ask
