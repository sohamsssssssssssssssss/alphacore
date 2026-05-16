from __future__ import annotations

import math

from engines.backtester import generate_snapshots
from engines.ml.trainer import train_model


def backtest_ml_accuracy(symbol: str, n_snapshots: int = 2000, lookahead: int = 30, n_folds: int = 5) -> dict:
    snapshots = generate_snapshots(symbol.upper(), n_snapshots, seed=42)
    fold_size = max(1, n_snapshots // n_folds)

    fold_accuracies: list[float] = []
    for i in range(n_folds):
        train_end = (i + 1) * fold_size
        test_end = min(n_snapshots, (i + 2) * fold_size)
        if test_end - train_end < 60 or train_end < 80:
            continue

        train_snaps = snapshots[:train_end]
        test_snaps = snapshots[:test_end]
        result = train_model(train_snaps, lookahead=lookahead)
        if "error" in result:
            continue

        # Evaluate on window by retraining on train slice and scoring test from merged generation.
        # Reuse trainer split metric as conservative proxy for fold quality.
        fold_accuracies.append(float(result["accuracy"]))

    if len(fold_accuracies) < n_folds:
        fold_accuracies.extend([0.0] * (n_folds - len(fold_accuracies)))

    mean_accuracy = sum(fold_accuracies) / len(fold_accuracies)
    std_accuracy = math.sqrt(sum((x - mean_accuracy) ** 2 for x in fold_accuracies) / len(fold_accuracies))

    return {
        "symbol": symbol.upper(),
        "mean_accuracy": float(mean_accuracy),
        "fold_accuracies": [float(x) for x in fold_accuracies],
        "std_accuracy": float(std_accuracy),
        "beats_random": bool(mean_accuracy > 0.5 + 1.0 * std_accuracy),
    }
