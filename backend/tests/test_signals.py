import numpy as np
import pandas as pd
import pytest

from engines.signals import (
    AmihudIlliquidity,
    IcebergPressure,
    MeanReversionSignal,
    IdiosyncraticVol,
    MomentumSignal,
    OrderFlowSignal,
    ResidualReversal,
    RsiDivergence,
    SpoofReversal,
    SpreadMomentum,
    VolumeSurge,
)


def test_each_new_signal_returns_float_or_series():
    prices = pd.Series(np.linspace(100, 110, 60))
    volume = pd.Series(np.linspace(1000, 2000, 60))
    rets = prices.pct_change().fillna(0.0)
    market = pd.Series(np.linspace(0.0005, 0.0015, 60))
    spreads = pd.Series(np.linspace(8.0, 4.0, 60))

    signals = [
        VolumeSurge().signal(volume),
        RsiDivergence().signal(prices),
        AmihudIlliquidity().signal(rets, volume),
        IdiosyncraticVol().signal(rets, market),
        ResidualReversal().signal(rets, market),
        SpreadMomentum().signal(spreads),
        IcebergPressure().signal(0.8, "BID", 120.0),
        SpoofReversal().signal(65.0, 0.02),
    ]

    for s in signals:
        assert isinstance(s, (float, pd.Series))


def test_iceberg_pressure_positive_for_bid():
    sig = IcebergPressure().signal(0.7, "BID", 200.0)
    assert sig > 0.0


def test_spoof_reversal_negative_when_spoof_and_price_up():
    sig = SpoofReversal().signal(80.0, 0.01)
    assert sig < 0.0


def test_volume_surge_zero_when_volume_equals_rolling_mean():
    volume = pd.Series([100.0] * 30)
    sig = VolumeSurge().signal(volume, window=20)
    assert abs(sig) < 1e-12


def _eval_signal(name: str, seed: int = 0, mode: str = "normal"):
    rng = np.random.default_rng(seed)
    prices = pd.Series(np.cumsum(rng.normal(0.1, 1.0, size=60)) + 100.0)
    volume = pd.Series(np.abs(rng.normal(1000.0, 100.0, size=60)))
    rets = prices.pct_change().fillna(0.0)
    market = pd.Series(rng.normal(0.0003, 0.01, size=60))
    spreads = pd.Series(np.abs(rng.normal(5.0, 1.0, size=60)))
    if mode == "empty":
        prices = pd.Series(dtype=float)
        volume = pd.Series(dtype=float)
        rets = pd.Series(dtype=float)
        market = pd.Series(dtype=float)
        spreads = pd.Series(dtype=float)
    elif mode == "zeros":
        prices = pd.Series([100.0] * 60)
        volume = pd.Series([0.0] * 60)
        rets = pd.Series([0.0] * 60)
        market = pd.Series([0.0] * 60)
        spreads = pd.Series([0.0] * 60)
    elif mode == "single":
        prices = pd.Series([100.0])
        volume = pd.Series([1000.0])
        rets = pd.Series([0.0])
        market = pd.Series([0.0])
        spreads = pd.Series([5.0])

    if name == "momentum":
        s = MomentumSignal()
        if mode == "empty":
            return s.compute("X")
        for i in range(max(1, len(prices))):
            s.update("X", float(prices.iloc[i]), None)
        out = s.compute("X")
        return float(out["signal"]) if out else 0.0
    if name == "mean_reversion":
        s = MeanReversionSignal()
        if mode == "empty":
            return s.compute("X")
        for i in range(max(1, len(prices))):
            s.update("X", float(prices.iloc[i]), None)
        out = s.compute("X")
        return float(out["signal"]) if out else 0.0
    if name == "order_flow":
        s = OrderFlowSignal()
        if mode == "empty":
            return s.compute("X")
        bids = [(100.0 - i * 0.1, 1000.0 - i * 10.0) for i in range(5)]
        asks = [(100.1 + i * 0.1, 1000.0 - i * 10.0) for i in range(5)]
        if mode == "zeros":
            bids = [(100.0, 0.0)] * 5
            asks = [(100.1, 0.0)] * 5
        s.update("X", bids, asks)
        out = s.compute("X")
        return float(out["signal"]) if out else 0.0
    if name == "volume_surge":
        return float(VolumeSurge().signal(volume))
    if name == "rsi_divergence":
        return float(RsiDivergence().signal(prices))
    if name == "amihud":
        return float(AmihudIlliquidity().signal(rets, volume))
    if name == "idio_vol":
        return float(IdiosyncraticVol().signal(rets, market))
    if name == "residual_reversal":
        return float(ResidualReversal().signal(rets, market))
    if name == "spread_momentum":
        return float(SpreadMomentum().signal(spreads))
    if name == "iceberg_pressure":
        return float(IcebergPressure().signal(0.8, "BID", 100.0 if mode != "zeros" else 0.0))
    if name == "spoof_reversal":
        score = 80.0 if mode != "zeros" else 0.0
        move = 0.01 if mode != "zeros" else 0.0
        return float(SpoofReversal().signal(score, move))
    raise ValueError(name)


SIGNAL_NAMES = [
    "momentum",
    "mean_reversion",
    "order_flow",
    "volume_surge",
    "rsi_divergence",
    "amihud",
    "idio_vol",
    "residual_reversal",
    "spread_momentum",
    "iceberg_pressure",
    "spoof_reversal",
]


@pytest.mark.parametrize("name", SIGNAL_NAMES)
def test_signal_returns_type_all_11(name):
    out = _eval_signal(name, seed=1, mode="normal")
    assert out is None or isinstance(out, float)


@pytest.mark.parametrize("name", SIGNAL_NAMES)
def test_signal_handles_empty_input(name):
    out = _eval_signal(name, seed=2, mode="empty")
    assert out is None or isinstance(out, float)


@pytest.mark.parametrize("name", SIGNAL_NAMES)
def test_signal_handles_all_zero_input(name):
    out = _eval_signal(name, seed=3, mode="zeros")
    assert out is None or isinstance(out, float)


@pytest.mark.parametrize("name", SIGNAL_NAMES)
def test_signal_single_data_point(name):
    out = _eval_signal(name, seed=4, mode="single")
    assert out is None or isinstance(out, float)


@pytest.mark.parametrize("name", SIGNAL_NAMES)
def test_signal_output_finite(name):
    out = _eval_signal(name, seed=5, mode="normal")
    if out is not None:
        assert np.isfinite(out)


@pytest.mark.parametrize("seed", list(range(30)))
@pytest.mark.parametrize("name", SIGNAL_NAMES)
def test_signal_randomized_robustness(name, seed):
    out = _eval_signal(name, seed=seed, mode="normal")
    assert out is None or np.isfinite(float(out))


@pytest.mark.parametrize("base,high", [(51.0, 80.0), (60.0, 90.0), (70.0, 99.0), (52.0, 75.0), (55.0, 88.0)])
def test_spoof_monotonicity(base, high):
    lo = SpoofReversal().signal(base, 0.01)
    hi = SpoofReversal().signal(high, 0.01)
    assert abs(hi) >= abs(lo)


@pytest.mark.parametrize("v1,v2", [(1000, 1500), (1000, 2000), (500, 1500), (1200, 2400), (800, 1600)])
def test_volume_surge_monotonicity(v1, v2):
    s = VolumeSurge()
    a = s.signal(pd.Series([v1] * 20 + [v1]), window=20)
    b = s.signal(pd.Series([v1] * 20 + [v2]), window=20)
    assert b >= a
