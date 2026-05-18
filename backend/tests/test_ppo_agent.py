import numpy as np
import pandas as pd

from engines.cost_model import CostModel
from engines.marl.hmm_regime import HmmRegimeDetector
from engines.marl.ppo_agent import PpoAgent


def _make_df(n: int = 500) -> pd.DataFrame:
    rng = np.random.default_rng(123)
    t = np.arange(n)
    mid = 1000.0 + np.cumsum(rng.normal(0.1, 1.0, size=n))
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=n, freq="min"),
            "mid_price": mid,
            "close": mid,
            "flow_imbalance": rng.normal(0, 1, size=n),
            "spread_bps": np.clip(rng.normal(5, 1.5, size=n), 1, 20),
            "realized_vol": np.abs(rng.normal(1.0, 0.3, size=n)),
            "iceberg_count": np.abs(rng.normal(2.0, 1.0, size=n)),
            "spoof_score": np.abs(rng.normal(30, 15, size=n)),
            "feat_a": rng.normal(0, 1, size=n),
            "feat_b": rng.normal(0, 1, size=n),
            "feat_c": rng.normal(0, 1, size=n),
            "feat_d": rng.normal(0, 1, size=n),
        }
    )
    return df


def test_env_and_agent_basic_behavior():
    df = _make_df(500)
    regime = HmmRegimeDetector(n_states=4)
    regime.fit(df)

    agent = PpoAgent(symbol_id="TEST", state_dim=10)
    env = agent.build_env(df=df, cost_model=CostModel(), regime_detector=regime)

    for _ in range(3):
        obs, _info = env.reset()
        done = False
        steps = 0
        while not done and steps < 20:
            action = int(steps % 3)
            obs, reward, terminated, truncated, _info = env.step(action)
            done = bool(terminated or truncated)
            assert isinstance(obs, np.ndarray)
            assert obs.shape == (10,)
            assert isinstance(reward, float)
            assert isinstance(done, bool)
            steps += 1

    action = agent.predict(np.zeros(10, dtype=float))
    assert isinstance(action, int)
    assert action in {0, 1, 2}
