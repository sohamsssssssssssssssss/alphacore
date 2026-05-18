from __future__ import annotations

from collections import defaultdict
import math

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
import numpy as np
import pandas as pd

from engines.backtester import Snapshot, generate_snapshots
from engines.cost_model import CostModel
from engines.ml.features import OrderBookFeatureEngine, build_dataset
from engines.ml.lstm_model import LSTMModel
from engines.purged_kfold import PurgedKFold
from engines.ml.trainer import predict, train_model


class MLEngine:
    def __init__(self):
        self._models: dict[str, bytes] = {}
        self._metrics: dict[str, dict] = {}
        self._history: dict[str, list[Snapshot]] = defaultdict(list)
        self._seed: dict[str, int] = defaultdict(lambda: 42)
        self._cv = PurgedKFold(n_splits=5, embargo_bars=5)

    def _evaluate_purged_cv(self, snapshots: list[Snapshot], lookahead: int = 30) -> dict:
        X_raw, y_raw = build_dataset(snapshots, lookahead)
        if len(X_raw) < 100:
            return {"error": "insufficient data"}

        X = np.asarray(X_raw, dtype=float)
        y = np.asarray(y_raw, dtype=int)
        timestamps = np.asarray([snapshots[i].timestamp for i in range(len(y_raw))], dtype=object)

        fold_accuracies: list[float] = []
        fold_f1: list[float] = []
        n_train_last = 0
        n_test_last = 0

        # Standard random K-fold leaks future information for time series because future
        # rows can influence training while earlier rows are in test. Use purged forward CV.
        for train_idx, test_idx in self._cv.split(X, y, timestamps):
            X_train, y_train = X[train_idx], y[train_idx]
            X_test, y_test = X[test_idx], y[test_idx]
            if len(X_train) < 50 or len(X_test) < 10:
                continue

            clf = RandomForestClassifier(n_estimators=100, random_state=42, max_depth=6, n_jobs=-1)
            clf.fit(X_train, y_train)
            pred = clf.predict(X_test)
            fold_accuracies.append(float(accuracy_score(y_test, pred)))
            fold_f1.append(float(f1_score(y_test, pred, zero_division=0)))
            n_train_last = int(len(X_train))
            n_test_last = int(len(X_test))

        if not fold_accuracies:
            return {"error": "insufficient data"}

        mean_acc = float(sum(fold_accuracies) / len(fold_accuracies))
        std_acc = float(math.sqrt(sum((x - mean_acc) ** 2 for x in fold_accuracies) / len(fold_accuracies)))
        mean_f1 = float(sum(fold_f1) / len(fold_f1))

        return {
            "accuracy_mean": mean_acc,
            "accuracy_std": std_acc,
            "accuracy": mean_acc,
            "f1_mean": mean_f1,
            "f1": mean_f1,
            "fold_accuracies": fold_accuracies,
            "n_train": n_train_last,
            "n_test": n_test_last,
            "n_folds": len(fold_accuracies),
        }

    def is_trained(self, symbol: str) -> bool:
        return symbol.upper() in self._models

    def _ensure_trained(self, symbol: str):
        sym = symbol.upper()
        if sym in self._models:
            return
        snaps = generate_snapshots(sym, 1000, seed=self._seed[sym])
        self._history[sym] = snaps
        cv_metrics = self._evaluate_purged_cv(snaps, lookahead=30)
        if "error" in cv_metrics:
            self._metrics[sym] = cv_metrics
            return
        res = train_model(snaps, lookahead=30)
        if "error" in res:
            self._metrics[sym] = res
            return
        self._models[sym] = res.pop("model_bytes")
        self._metrics[sym] = cv_metrics

    def get_signal(self, symbol: str) -> dict:
        sym = symbol.upper()
        self._ensure_trained(sym)
        if sym not in self._models:
            return {"symbol": sym, "error": "insufficient data"}

        # Append one synthetic new snapshot for drift.
        seed = self._seed[sym] + 1
        self._seed[sym] = seed
        new_snap = generate_snapshots(sym, 1, seed=seed)[0]
        self._history[sym].append(new_snap)

        pred = predict(self._models[sym], self._history[sym], len(self._history[sym]) - 1)
        return {
            "symbol": sym,
            **pred,
            "training": {
                "accuracy_mean": float(self._metrics[sym].get("accuracy_mean", 0.0)),
                "accuracy_std": float(self._metrics[sym].get("accuracy_std", 0.0)),
                "f1_mean": float(self._metrics[sym].get("f1_mean", 0.0)),
            },
        }

    def retrain(self, symbol: str) -> dict:
        sym = symbol.upper()
        snaps = generate_snapshots(sym, 1000, seed=self._seed[sym] + 100)
        self._history[sym] = snaps
        cv_metrics = self._evaluate_purged_cv(snaps, lookahead=30)
        if "error" in cv_metrics:
            self._metrics[sym] = cv_metrics
            return {"symbol": sym, **cv_metrics}
        res = train_model(snaps, lookahead=30)
        if "error" in res:
            self._metrics[sym] = res
            return {"symbol": sym, **res}
        self._models[sym] = res.pop("model_bytes")
        self._metrics[sym] = cv_metrics
        return {"symbol": sym, **cv_metrics}

    def get_metrics(self, symbol: str) -> dict:
        sym = symbol.upper()
        self._ensure_trained(sym)
        return {"symbol": sym, **self._metrics.get(sym, {"error": "insufficient data"})}


ml_engine = MLEngine()


class MultiModelEngine:
    def __init__(self, feature_engine: OrderBookFeatureEngine, purged_kfold: PurgedKFold, cost_model: CostModel):
        self.feature_engine = feature_engine
        self.purged_kfold = purged_kfold
        self.cost_model = cost_model
        self.results: dict[str, dict] = {}

    @staticmethod
    def _sharpe_from_acc(accs: list[float]) -> float:
        if len(accs) < 2:
            return 0.0
        r = np.asarray(accs, dtype=float) - 0.5
        s = float(np.std(r))
        if s == 0.0:
            return 0.0
        return float(np.mean(r) / s * np.sqrt(252.0))

    @staticmethod
    def _softmax(x: np.ndarray) -> np.ndarray:
        z = x - np.max(x)
        e = np.exp(z)
        return e / np.sum(e)

    def _fit_eval_model(self, model_name: str, model, X: np.ndarray, y: np.ndarray, timestamps: np.ndarray) -> dict:
        fold_acc: list[float] = []
        for train_idx, test_idx in self.purged_kfold.split(X, y, timestamps):
            X_train, y_train = X[train_idx], y[train_idx]
            X_test, y_test = X[test_idx], y[test_idx]
            if len(X_train) < 20 or len(X_test) < 5:
                continue

            if model_name == "lstm":
                classes = int(np.max(y_train)) + 1
                m = LSTMModel(input_dim=X.shape[1], output_dim=max(3, classes))
                m.fit(X_train[:, None, :], y_train, epochs=2, lr=1e-3)
                pred = m.predict(X_test[:, None, :])
            else:
                m = model
                m.fit(X_train, y_train)
                pred = m.predict(X_test)

            fold_acc.append(float(accuracy_score(y_test, pred)))

        mean_acc = float(np.mean(fold_acc)) if fold_acc else 0.0
        std_acc = float(np.std(fold_acc)) if fold_acc else 0.0
        sharpe_contrib = self._sharpe_from_acc(fold_acc)

        # Fit final model on full data for inference.
        if model_name == "lstm":
            classes = int(np.max(y)) + 1
            final_model = LSTMModel(input_dim=X.shape[1], output_dim=max(3, classes))
            final_model.fit(X[:, None, :], y, epochs=2, lr=1e-3)
        else:
            final_model = model
            final_model.fit(X, y)

        return {
            "mean_acc": mean_acc,
            "std_acc": std_acc,
            "model_object": final_model,
            "walk_forward_sharpe": float(sharpe_contrib),
            "fold_accuracies": fold_acc,
        }

    def train_all(self, df: pd.DataFrame, target_col: str) -> dict:
        if target_col not in df.columns:
            raise ValueError(f"target column '{target_col}' not found")

        y = df[target_col].to_numpy(dtype=int)
        X_df = df.drop(columns=[target_col])
        if "timestamp" in X_df.columns:
            timestamps = X_df["timestamp"].to_numpy()
            X_df = X_df.drop(columns=["timestamp"])
        else:
            timestamps = np.arange(len(df))
        X = X_df.to_numpy(dtype=float)

        models = {
            "random_forest": RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=1),
            "xgboost": XGBClassifier(
                n_estimators=40,
                max_depth=4,
                learning_rate=0.1,
                subsample=0.9,
                colsample_bytree=0.9,
                eval_metric="logloss",
                random_state=42,
                n_jobs=1,
            ),
            "lightgbm": LGBMClassifier(n_estimators=40, random_state=42, verbosity=-1, n_jobs=1),
            "lstm": None,
        }

        out: dict[str, dict] = {}
        for name, model in models.items():
            out[name] = self._fit_eval_model(name, model, X, y, np.asarray(timestamps))

        self.results = out
        return out

    def compare(self) -> pd.DataFrame:
        if not self.results:
            return pd.DataFrame(columns=["model", "mean_accuracy", "std_accuracy", "sharpe_contribution"])

        rows = []
        for model, m in self.results.items():
            rows.append(
                {
                    "model": model,
                    "mean_accuracy": float(m["mean_acc"]),
                    "std_accuracy": float(m["std_acc"]),
                    "sharpe_contribution": float(m["walk_forward_sharpe"]),
                }
            )
        table = pd.DataFrame(rows).sort_values("mean_accuracy", ascending=False).reset_index(drop=True)
        print(table.to_string(index=False))
        return table

    def ensemble_predict(self, X: np.ndarray) -> np.ndarray:
        if not self.results:
            raise RuntimeError("train_all must be called before ensemble_predict")
        Xn = np.asarray(X, dtype=float)

        model_names = list(self.results.keys())
        sharpes = np.asarray([float(self.results[k]["walk_forward_sharpe"]) for k in model_names], dtype=float)
        weights = self._softmax(sharpes)

        preds = []
        for k in model_names:
            model = self.results[k]["model_object"]
            if hasattr(model, "predict_proba"):
                p = model.predict_proba(Xn)
                p1 = p[:, 1] if p.ndim == 2 and p.shape[1] > 1 else p.reshape(-1)
            elif isinstance(model, LSTMModel):
                p = model.predict_proba(Xn[:, None, :])
                p1 = p[:, 1] if p.shape[1] > 1 else p[:, 0]
            else:
                p1 = np.asarray(model.predict(Xn), dtype=float)
            preds.append(np.asarray(p1, dtype=float))

        mat = np.vstack(preds)
        combined = np.average(mat, axis=0, weights=weights)
        return (combined >= 0.5).astype(int)
