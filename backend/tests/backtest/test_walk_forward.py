from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.walk_forward import WalkForwardBacktester
from engines.backtest_metrics import deflated_sharpe_ratio
from engines.cost_model import CostModel
from engines.ml.features import OrderBookFeatureEngine


class _MajorityModel:
    def __init__(self):
        self.label = 0

    def fit(self, x, y):
        vals, counts = np.unique(y, return_counts=True)
        self.label = int(vals[np.argmax(counts)]) if len(vals) else 0
        return self

    def predict(self, x):
        return np.full(len(x), self.label, dtype=int)


def _synthetic_df(n_rows: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    df = pd.DataFrame({f"f{i:02d}": rng.normal(size=n_rows) for i in range(42)})
    df["timestamp"] = pd.date_range("2024-01-01", periods=n_rows, freq="D", tz="UTC")
    df["target"] = (rng.normal(size=n_rows) > 0).astype(int)
    return df


def test_rolling_windows():
    df = _synthetic_df(200)
    wfb = WalkForwardBacktester(df=df, cost_model=CostModel(), feature_engine=OrderBookFeatureEngine(use_cpp=False))
    _ = wfb.run_evaluation(models={"RF": _MajorityModel()}, train_window_days=30, test_window_days=10)

    assert len(wfb.window_splits) > 0
    for split in wfb.window_splits:
        assert split.test_start > split.train_end
        assert set(split.train_index).isdisjoint(set(split.test_index))


def test_report_metrics():
    cm = CostModel(k_impact=0.0, brokerage_per_trade=20.0, stt_rate=0.000005)
    gross_per_trade = 1000.0
    n_trades = 10

    costs = [cm.total_cost(price=1_000_000.0, qty=1.0, adv=1.0, spread_bps=0.0, side="SELL") for _ in range(n_trades)]
    net_pnls = [gross_per_trade - c for c in costs]
    total_net = float(sum(net_pnls))

    assert round(costs[0], 6) == 25.0
    assert round(total_net, 6) == 9750.0

    returns = np.asarray(net_pnls, dtype=float)
    dsr_payload = deflated_sharpe_ratio(returns)
    assert float(dsr_payload["dsr"]) <= float(dsr_payload["raw_sharpe"])


def test_dsr_gate_filters_low_dsr_models():
    summary = pd.DataFrame({
        "model": ["RF", "XGB", "LGBM", "LSTM"],
        "mean_accuracy": [0.55, 0.52, 0.53, 0.51],
        "std_accuracy": [0.05, 0.04, 0.04, 0.06],
        "total_net_pnl": [1000.0, 800.0, 900.0, 700.0],
        "dsr": [0.97, 0.43, 0.96, 0.21],
        "win_rate": [0.55, 0.52, 0.53, 0.51],
        "purged_cv_acc": [0.55, 0.52, 0.53, 0.51],
    })
    passed = WalkForwardBacktester.apply_dsr_gate(summary, threshold=0.95)
    assert list(passed["model"]) == ["RF", "LGBM"]
    assert all(passed["dsr"] > 0.95)


def test_stationary_bootstrap_sharpe_ci():
    from engines.backtest_metrics import stationary_bootstrap_sharpe_ci
    rng = np.random.default_rng(0)

    # Strong positive signal — CI should be reliable
    strong = rng.normal(0.005, 0.01, 1000)
    result = stationary_bootstrap_sharpe_ci(strong, n_bootstrap=500)
    assert result["ci_lower"] < result["sharpe"] < result["ci_upper"]
    assert result["ci_width"] > 0
    assert result["reliable"] is True

    # Noise — CI should cross zero, not reliable
    noise = rng.normal(0.0, 0.02, 200)
    result2 = stationary_bootstrap_sharpe_ci(noise, n_bootstrap=500)
    assert result2["ci_lower"] < result2["ci_upper"]
    assert result2["reliable"] is False

    # Edge case — too few observations
    result3 = stationary_bootstrap_sharpe_ci([0.001])
    assert result3["sharpe"] == 0.0
    assert result3["reliable"] is False
