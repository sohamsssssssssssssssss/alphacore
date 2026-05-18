from __future__ import annotations

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM


class HmmRegimeDetector:
    def __init__(self, n_states: int = 4, feature_cols: list[str] | None = None):
        self.n_states = int(n_states)
        self.feature_cols = feature_cols or [
            "flow_imbalance",
            "spread_bps",
            "realized_vol",
            "iceberg_count",
            "spoof_score",
        ]
        self.model: GaussianHMM | None = None
        self.means_: pd.Series | None = None
        self.stds_: pd.Series | None = None
        self.state_labels_: dict[int, str] | None = None

    def _prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        x = df[self.feature_cols].copy()
        return x.fillna(0.0).astype(float)

    def fit(self, df: pd.DataFrame) -> "HmmRegimeDetector":
        x = self._prepare_features(df)
        self.means_ = x.mean(axis=0)
        stds = x.std(axis=0).replace(0.0, 1.0)
        self.stds_ = stds

        z = (x - self.means_) / self.stds_
        self.model = GaussianHMM(n_components=self.n_states, covariance_type="full", n_iter=100, random_state=42)
        self.model.fit(z.to_numpy())

        states = self.model.predict(z.to_numpy())
        labeled_df = x.copy()
        labeled_df["state"] = states
        self.state_labels_ = self.label_states(labeled_df)
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        if self.model is None or self.means_ is None or self.stds_ is None:
            raise RuntimeError("Model not fitted")
        x = self._prepare_features(df)
        z = (x - self.means_) / self.stds_
        return self.model.predict(z.to_numpy())

    def label_states(self, df: pd.DataFrame) -> dict[int, str]:
        data = df.copy()
        if "state" not in data.columns:
            states = self.predict(data)
            data["state"] = states

        out: dict[int, str] = {}
        for s in range(self.n_states):
            sub = data[data["state"] == s]
            if sub.empty:
                out[s] = "mean-reverting"
                continue

            spread = float(sub["spread_bps"].mean())
            vol = float(sub["realized_vol"].mean())
            flow_imb = float(sub["flow_imbalance"].abs().mean())
            iceberg = float(sub["iceberg_count"].mean())

            if spread >= float(data["spread_bps"].quantile(0.7)) and iceberg <= float(data["iceberg_count"].quantile(0.3)):
                out[s] = "illiquid"
            elif vol >= float(data["realized_vol"].quantile(0.7)):
                out[s] = "volatile"
            elif flow_imb >= float(data["flow_imbalance"].abs().quantile(0.7)):
                out[s] = "trending"
            else:
                out[s] = "mean-reverting"

        self.state_labels_ = out
        return out

    def get_current_regime(self, latest_row: pd.Series) -> str:
        if self.model is None:
            raise RuntimeError("Model not fitted")
        row_df = pd.DataFrame([latest_row])[self.feature_cols].astype(float)
        state = int(self.predict(row_df)[0])
        if not self.state_labels_:
            return str(state)
        return self.state_labels_.get(state, str(state))
