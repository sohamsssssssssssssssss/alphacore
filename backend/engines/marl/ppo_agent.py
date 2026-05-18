from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from engines.cost_model import CostModel
from engines.marl.hmm_regime import HmmRegimeDetector
from engines.marl.trading_env import TradingEnv

try:
    from stable_baselines3 import PPO
    _HAS_SB3 = True
except Exception:  # pragma: no cover
    PPO = None
    _HAS_SB3 = False


class PpoAgent:
    def __init__(
        self,
        symbol_id: str,
        state_dim: int,
        action_dim: int = 3,
        lr: float = 3e-4,
        gamma: float = 0.99,
        clip_eps: float = 0.2,
    ):
        self.symbol_id = symbol_id
        self.state_dim = int(state_dim)
        self.action_dim = int(action_dim)
        self.lr = float(lr)
        self.gamma = float(gamma)
        self.clip_eps = float(clip_eps)

        self.model = None
        self.env: TradingEnv | None = None
        self.cost_model: CostModel | None = None
        self.regime_detector: HmmRegimeDetector | None = None

    def build_env(self, df: pd.DataFrame, cost_model: CostModel, regime_detector: HmmRegimeDetector) -> TradingEnv:
        self.cost_model = cost_model
        self.regime_detector = regime_detector
        self.env = TradingEnv(df=df, state_dim=self.state_dim, cost_model=cost_model, regime_detector=regime_detector)
        return self.env

    def train(self, df: pd.DataFrame, total_timesteps: int = 100_000) -> None:
        if self.cost_model is None:
            self.cost_model = CostModel()
        if self.regime_detector is None:
            self.regime_detector = HmmRegimeDetector()
            self.regime_detector.fit(df)

        env = self.build_env(df, self.cost_model, self.regime_detector)

        models_dir = Path("models")
        models_dir.mkdir(parents=True, exist_ok=True)
        model_path = models_dir / f"ppo_{self.symbol_id}.zip"

        if _HAS_SB3:
            self.model = PPO(
                "MlpPolicy",
                env,
                learning_rate=self.lr,
                gamma=self.gamma,
                clip_range=self.clip_eps,
                verbose=0,
            )
            self.model.learn(total_timesteps=int(total_timesteps))
            self.model.save(str(model_path))
        else:
            # Minimal fallback policy: save average return sign to emulate a simple policy.
            mids = df["mid_price"].astype(float).to_numpy()
            drift = float(np.mean(np.diff(mids))) if len(mids) > 1 else 0.0
            self.model = {"fallback": True, "drift": drift}
            np.savez(str(model_path).replace(".zip", ".npz"), drift=drift)

    def predict(self, state: np.ndarray) -> int:
        s = np.asarray(state, dtype=float)
        if _HAS_SB3 and self.model is not None:
            action, _ = self.model.predict(s, deterministic=True)
            return int(action)

        # Fallback heuristic: use regime + pnl/position tail when available.
        if s.size >= 3:
            regime = int(round(s[-1]))
            if regime == 2:  # volatile
                return 2
            if regime == 0:  # trending
                return 0
        return 2
