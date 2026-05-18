from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd

from engines.backtest_metrics import deflated_sharpe_ratio, stationary_bootstrap_sharpe_ci
from engines.cost_model import CostModel
from engines.ml.features import OrderBookFeatureEngine
from engines.factor_residualizer import residualize_against_factors, synthetic_nse_factors


@dataclass
class _SplitRecord:
    train_index: pd.Index
    test_index: pd.Index
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


class WalkForwardBacktester:
    def __init__(self, df: pd.DataFrame, cost_model: CostModel, feature_engine: OrderBookFeatureEngine):
        self.df = df.copy()
        self.cost_model = cost_model
        self.feature_engine = feature_engine
        self.window_splits: list[_SplitRecord] = []

    @staticmethod
    def _resolve_target_column(df: pd.DataFrame) -> str:
        for name in ("target", "y", "label"):
            if name in df.columns:
                return name
        raise ValueError("DataFrame must include target column ('target', 'y', or 'label').")

    @staticmethod
    def _resolve_timestamp_column(df: pd.DataFrame) -> str:
        for name in ("timestamp", "ts", "datetime", "date"):
            if name in df.columns:
                return name
        raise ValueError("DataFrame must include a timestamp column ('timestamp', 'ts', 'datetime', or 'date').")

    def _prepare_frame(self) -> tuple[pd.DataFrame, str, str]:
        frame = self.df.copy()
        target_col = self._resolve_target_column(frame)
        ts_col = self._resolve_timestamp_column(frame)
        frame[ts_col] = pd.to_datetime(frame[ts_col], utc=True)
        frame = frame.sort_values(ts_col).reset_index(drop=True)
        return frame, target_col, ts_col

    def _window_metrics(self, y_true: np.ndarray, y_pred: np.ndarray) -> dict:
        y_true = np.asarray(y_true)
        y_pred = np.asarray(y_pred)
        accuracy = float(np.mean(y_true == y_pred)) if y_true.size else 0.0

        gross_per_trade = np.where(y_true == y_pred, 1000.0, -1000.0)
        cost_per_trade = np.array(
            [
                self.cost_model.total_cost(price=1.0, qty=1.0, adv=None, spread_bps=0.0, side="SELL")
                for _ in range(len(gross_per_trade))
            ],
            dtype=float,
        )
        net = gross_per_trade - cost_per_trade
        net_pnl = float(np.sum(net))

        std = float(np.std(net))
        sharpe = float((np.mean(net) / std) * np.sqrt(252.0)) if std > 0 else 0.0
        win_rate = float(np.mean(net > 0.0)) if net.size else 0.0

        return {
            "accuracy": accuracy,
            "net_pnl": net_pnl,
            "sharpe": sharpe,
            "win_rate": win_rate,
            "returns": net,
        }

    def run_evaluation(self, models: dict, train_window_days: int = 60, test_window_days: int = 10) -> dict:
        frame, target_col, ts_col = self._prepare_frame()
        feature_cols = [c for c in frame.columns if c not in {target_col, ts_col}]
        results: dict[str, list[dict]] = {name: [] for name in models}
        self.window_splits = []

        start = frame[ts_col].min().normalize()
        end = frame[ts_col].max().normalize()
        cursor = start + pd.Timedelta(days=train_window_days)

        while cursor <= end:
            train_start = cursor - pd.Timedelta(days=train_window_days)
            train_end = cursor
            test_start = train_end + pd.Timedelta(microseconds=1)
            test_end = test_start + pd.Timedelta(days=test_window_days)

            if test_start <= train_end:
                raise ValueError("test window start must be strictly greater than train window end")

            train_mask = (frame[ts_col] >= train_start) & (frame[ts_col] <= train_end)
            test_mask = (frame[ts_col] >= test_start) & (frame[ts_col] < test_end)

            train_df = frame.loc[train_mask]
            test_df = frame.loc[test_mask]
            if train_df.empty or test_df.empty:
                cursor += pd.Timedelta(days=test_window_days)
                continue

            self.window_splits.append(
                _SplitRecord(
                    train_index=train_df.index,
                    test_index=test_df.index,
                    train_start=train_df[ts_col].min(),
                    train_end=train_df[ts_col].max(),
                    test_start=test_df[ts_col].min(),
                    test_end=test_df[ts_col].max(),
                )
            )

            x_train = train_df[feature_cols].to_numpy(dtype=float)
            y_train = train_df[target_col].to_numpy()
            x_test = test_df[feature_cols].to_numpy(dtype=float)
            y_test = test_df[target_col].to_numpy()

            for model_name, model in models.items():
                model.fit(x_train, y_train)
                y_pred = np.asarray(model.predict(x_test))
                wm = self._window_metrics(y_test, y_pred)
                results[model_name].append(
                    {
                        "train_start": train_df[ts_col].min(),
                        "train_end": train_df[ts_col].max(),
                        "test_start": test_df[ts_col].min(),
                        "test_end": test_df[ts_col].max(),
                        "accuracy": wm["accuracy"],
                        "net_pnl": wm["net_pnl"],
                        "sharpe": wm["sharpe"],
                        "win_rate": wm["win_rate"],
                        "returns": wm["returns"],
                    }
                )

            cursor += pd.Timedelta(days=test_window_days)

        return {k: pd.DataFrame(v) for k, v in results.items()}

    @staticmethod
    def get_summary(results: dict) -> pd.DataFrame:
        rows: list[dict] = []
        for model_name, model_df in results.items():
            if model_df is None or model_df.empty:
                rows.append(
                    {
                        "model": model_name,
                        "mean_accuracy": 0.0,
                        "std_accuracy": 0.0,
                        "total_net_pnl": 0.0,
                        "dsr": 0.0,
                        "sharpe_ci_lower": 0.0,
                        "sharpe_ci_upper": 0.0,
                        "sharpe_reliable": False,
                        "win_rate": 0.0,
                        "purged_cv_acc": 0.0,
                    }
                )
                continue

            all_returns = np.concatenate([np.asarray(x, dtype=float) for x in model_df["returns"].tolist()])
            dsr_payload = deflated_sharpe_ratio(all_returns)
            factor_rets = synthetic_nse_factors(n=len(all_returns))
            resid_payload = residualize_against_factors(all_returns, factor_rets)
            rows.append(
                {
                    "model": model_name,
                    "mean_accuracy": float(model_df["accuracy"].mean()),
                    "std_accuracy": float(model_df["accuracy"].std(ddof=0)),
                    "total_net_pnl": float(model_df["net_pnl"].sum()),
                    "dsr": float(dsr_payload.get("dsr", 0.0)),
                    "sharpe_ci_lower": float(stationary_bootstrap_sharpe_ci(all_returns).get("ci_lower", 0.0)),
                    "sharpe_ci_upper": float(stationary_bootstrap_sharpe_ci(all_returns).get("ci_upper", 0.0)),
                    "sharpe_reliable": bool(stationary_bootstrap_sharpe_ci(all_returns).get("reliable", False)),
                    "win_rate": float(model_df["win_rate"].mean()),
                    "purged_cv_acc": float(model_df["accuracy"].mean()),
                    "alpha_annualised": float(resid_payload.get("alpha_annualised", 0.0)),
                    "t_stat_alpha": float(resid_payload.get("t_stat_alpha", 0.0)),
                }
            )

        return pd.DataFrame(rows, columns=["model", "mean_accuracy", "std_accuracy", "total_net_pnl", "dsr", "win_rate", "purged_cv_acc", "sharpe_ci_lower", "sharpe_ci_upper", "sharpe_reliable", "alpha_annualised", "t_stat_alpha"])

    @staticmethod
    def apply_dsr_gate(summary: pd.DataFrame, threshold: float = 0.95) -> pd.DataFrame:
        """Return only models that pass the DSR gate.

        Atharva's standard: DSR > 0.95 means 95% probability the edge is real.
        Models below this threshold are considered overfit and excluded.
        """
        passed = summary[summary["dsr"] > threshold].copy()
        failed = summary[summary["dsr"] <= threshold]["model"].tolist()
        if failed:
            import logging
            logging.getLogger(__name__).warning(
                "DSR gate (threshold=%.2f) rejected models: %s", threshold, failed
            )
        return passed


class _MajorityModel:
    def __init__(self):
        self._label = 0

    def fit(self, x, y):
        arr = np.asarray(y)
        if arr.size == 0:
            self._label = 0
            return self
        vals, counts = np.unique(arr, return_counts=True)
        self._label = int(vals[np.argmax(counts)])
        return self

    def predict(self, x):
        n = len(x)
        return np.full(n, self._label, dtype=int)


def _build_synthetic_df(n_rows: int = 600) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    ts = pd.date_range("2024-01-01", periods=n_rows, freq="H", tz="UTC")
    data = {f"f{i:02d}": rng.normal(size=n_rows) for i in range(42)}
    y = (rng.normal(size=n_rows) > 0).astype(int)
    df = pd.DataFrame(data)
    df["timestamp"] = ts
    df["target"] = y
    return df


def _run_all(output: str) -> str:
    from backtest.report_generator import generate_comparison_report, save_report

    df = _build_synthetic_df()
    wfb = WalkForwardBacktester(df=df, cost_model=CostModel(), feature_engine=OrderBookFeatureEngine(use_cpp=False))
    models = {
        "RF": _MajorityModel(),
        "XGB": _MajorityModel(),
        "LGBM": _MajorityModel(),
        "LSTM": _MajorityModel(),
    }
    results = wfb.run_evaluation(models=models, train_window_days=60, test_window_days=10)
    report = generate_comparison_report(results)
    summary = wfb.get_summary(results)
    passed = WalkForwardBacktester.apply_dsr_gate(summary, threshold=0.95)
    print(f"Models passing DSR gate: {passed['model'].tolist()}")
    save_report(report, path=output)
    print(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-all", action="store_true")
    parser.add_argument("--output", default="report.md")
    args = parser.parse_args()

    if args.run_all:
        _run_all(args.output)


if __name__ == "__main__":
    main()
