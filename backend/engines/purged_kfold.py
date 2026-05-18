from __future__ import annotations

import numpy as np


class PurgedKFold:
    def __init__(self, n_splits: int = 5, embargo_bars: int = 5):
        if n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        if embargo_bars < 0:
            raise ValueError("embargo_bars must be >= 0")
        self.n_splits = int(n_splits)
        self.embargo_bars = int(embargo_bars)

    def get_n_splits(self) -> int:
        return self.n_splits

    def split(self, X, y, timestamps):
        n_samples = len(timestamps)
        if len(X) != n_samples or len(y) != n_samples:
            raise ValueError("X, y, and timestamps must have the same length")
        if n_samples < self.n_splits:
            raise ValueError("n_samples must be >= n_splits")

        indices = np.arange(n_samples)
        fold_blocks = np.array_split(indices, self.n_splits)

        # Time-ordered expanding-train / forward-test splits.
        for k in range(1, self.n_splits):
            test_idx = fold_blocks[k]
            if test_idx.size == 0:
                continue

            test_start = int(test_idx[0])
            train_end = max(0, test_start - self.embargo_bars)
            train_idx = indices[:train_end]

            if train_idx.size == 0:
                continue

            yield train_idx, test_idx
