from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

try:
    import gymnasium as gym
    from gymnasium import spaces
except Exception:  # pragma: no cover
    import gym as gym  # type: ignore
    from gym import spaces  # type: ignore

from engines.cost_model import CostModel
from engines.marl.hmm_regime import HmmRegimeDetector


class TradingEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(
        self,
        df: pd.DataFrame,
        state_dim: int,
        cost_model: CostModel,
        regime_detector: HmmRegimeDetector,
    ):
        super().__init__()
        self.df = df.reset_index(drop=True).copy()
        self.state_dim = int(state_dim)
        self.cost_model = cost_model
        self.regime_detector = regime_detector

        if "mid_price" not in self.df.columns:
            if "close" in self.df.columns:
                self.df["mid_price"] = self.df["close"].astype(float)
            else:
                raise ValueError("DataFrame must include 'mid_price' or 'close'")

        self.regime_states = self.regime_detector.predict(self.df)

        self.feature_cols = [
            c
            for c in self.df.columns
            if c not in {"timestamp", "symbol", "mid_price"} and pd.api.types.is_numeric_dtype(self.df[c])
        ]
        self.base_dim = max(1, self.state_dim - 3)

        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(self.state_dim,),
            dtype=np.float32,
        )
        self.action_space = spaces.Discrete(3)

        self.idx = 0
        self.position = 0  # -1 short, 0 flat, 1 long
        self.entry_price = 0.0
        self.realized_pnl = 0.0

    def _row_to_features(self, idx: int) -> np.ndarray:
        row = self.df.iloc[idx]
        vals = [float(row[c]) for c in self.feature_cols[: self.base_dim]]
        if len(vals) < self.base_dim:
            vals.extend([0.0] * (self.base_dim - len(vals)))
        return np.asarray(vals, dtype=np.float32)

    def _obs(self) -> np.ndarray:
        base = self._row_to_features(self.idx)
        regime = float(self.regime_states[self.idx]) if len(self.regime_states) > self.idx else 0.0
        tail = np.asarray([float(self.position), float(self.realized_pnl), regime], dtype=np.float32)
        obs = np.concatenate([base, tail], axis=0)
        return obs.astype(np.float32)

    def reset(self, *, seed: int | None = None, options: dict[str, Any] | None = None):
        super().reset(seed=seed)
        self.idx = 0
        self.position = 0
        self.entry_price = 0.0
        self.realized_pnl = 0.0
        return self._obs(), {}

    def step(self, action: int):
        action = int(action)
        row = self.df.iloc[self.idx]
        price = float(row["mid_price"])
        spread_bps = float(row["spread_bps"]) if "spread_bps" in row else 5.0
        qty = 1.0

        reward = 0.0

        if action == 0:  # LONG
            if self.position == -1:
                pnl = (self.entry_price - price) * qty
                self.realized_pnl += pnl
                reward += pnl
            self.position = 1
            self.entry_price = price
            reward -= self.cost_model.total_cost(price, qty, None, spread_bps, side="BUY")
        elif action == 1:  # SHORT
            if self.position == 1:
                pnl = (price - self.entry_price) * qty
                self.realized_pnl += pnl
                reward += pnl
            self.position = -1
            self.entry_price = price
            reward -= self.cost_model.total_cost(price, qty, None, spread_bps, side="SELL")
        else:  # FLAT
            if self.position == 1:
                pnl = (price - self.entry_price) * qty
                self.realized_pnl += pnl
                reward += pnl
                reward -= self.cost_model.total_cost(price, qty, None, spread_bps, side="SELL")
            elif self.position == -1:
                pnl = (self.entry_price - price) * qty
                self.realized_pnl += pnl
                reward += pnl
                reward -= self.cost_model.total_cost(price, qty, None, spread_bps, side="BUY")
            self.position = 0

        self.idx += 1
        terminated = self.idx >= len(self.df)
        truncated = False

        if terminated and self.position != 0:
            reward -= self.cost_model.brokerage_per_trade
            self.position = 0

        next_obs = self._obs() if not terminated else np.zeros((self.state_dim,), dtype=np.float32)
        return next_obs, float(reward), bool(terminated), bool(truncated), {}
