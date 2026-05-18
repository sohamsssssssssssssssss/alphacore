import numpy as np
import pandas as pd

from engines.cost_model import CostModel
from engines.ml.features import OrderBookFeatureEngine
from engines.ml.ml_engine import MultiModelEngine
from engines.purged_kfold import PurgedKFold


class _DummyModel:
    def fit(self, X, y):
        return self

    def predict(self, X):
        return np.zeros(len(X), dtype=int)

    def predict_proba(self, X):
        n = len(X)
        out = np.zeros((n, 2), dtype=float)
        out[:, 1] = 0.6
        out[:, 0] = 0.4
        return out


def _synthetic_df(n: int = 200, d: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    X = rng.normal(0, 1, size=(n, d))
    cols = [f"f{i}" for i in range(d)]
    df = pd.DataFrame(X, columns=cols)
    score = X[:, 0] * 0.7 + X[:, 1] * 0.2 - X[:, 2] * 0.1
    y = (score > np.median(score)).astype(int)
    df["timestamp"] = np.arange(n)
    df["target"] = y
    return df


def test_multi_model_training_compare_ensemble():
    df = _synthetic_df()

    mme = MultiModelEngine(
        feature_engine=OrderBookFeatureEngine(use_cpp=False),
        purged_kfold=PurgedKFold(n_splits=5, embargo_bars=5),
        cost_model=CostModel(),
    )

    mme.results = {
        "random_forest": {"mean_acc": 0.55, "std_acc": 0.02, "model_object": _DummyModel(), "walk_forward_sharpe": 0.2},
        "xgboost": {"mean_acc": 0.57, "std_acc": 0.03, "model_object": _DummyModel(), "walk_forward_sharpe": 0.3},
        "lightgbm": {"mean_acc": 0.56, "std_acc": 0.02, "model_object": _DummyModel(), "walk_forward_sharpe": 0.25},
        "lstm": {"mean_acc": 0.54, "std_acc": 0.04, "model_object": _DummyModel(), "walk_forward_sharpe": 0.1},
    }

    cmp_df = mme.compare()
    assert len(cmp_df) == 4

    X_pred = df[[c for c in df.columns if c.startswith("f")]].to_numpy(dtype=float)
    pred = mme.ensemble_predict(X_pred)
    assert len(pred) == len(df)
