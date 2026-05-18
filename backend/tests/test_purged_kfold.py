import numpy as np
import pytest

from engines.purged_kfold import PurgedKFold


def _build_synthetic(n: int = 1000):
    X = np.arange(n).reshape(n, 1)
    y = (np.arange(n) % 2).astype(int)
    ts = np.array([f"2025-01-01T00:{i:04d}:00" for i in range(n)], dtype=object)
    return X, y, ts


def test_test_indices_strictly_after_train_indices():
    X, y, ts = _build_synthetic(1000)
    cv = PurgedKFold(n_splits=5, embargo_bars=5)
    for train_idx, test_idx in cv.split(X, y, ts):
        assert train_idx.max() < test_idx.min()


def test_embargo_removes_samples_within_5_bars_of_boundary():
    X, y, ts = _build_synthetic(1000)
    cv = PurgedKFold(n_splits=5, embargo_bars=5)

    for train_idx, test_idx in cv.split(X, y, ts):
        boundary = int(test_idx.min())
        # The final training index must be at most boundary - embargo - 1.
        assert train_idx.max() <= boundary - 6


def test_no_data_leakage_no_overlap_between_train_and_test():
    X, y, ts = _build_synthetic(1000)
    cv = PurgedKFold(n_splits=5, embargo_bars=5)

    for train_idx, test_idx in cv.split(X, y, ts):
        assert len(set(train_idx).intersection(set(test_idx))) == 0


def test_1000_samples_5_folds_structure():
    X, y, ts = _build_synthetic(1000)
    cv = PurgedKFold(n_splits=5, embargo_bars=5)
    splits = list(cv.split(X, y, ts))

    assert cv.get_n_splits() == 5
    assert len(splits) == 4
    for train_idx, test_idx in splits:
        assert len(train_idx) > 0
        assert len(test_idx) > 0


def test_n_splits_3_forward_folds_count():
    X, y, ts = _build_synthetic(300)
    cv = PurgedKFold(n_splits=3, embargo_bars=5)
    splits = list(cv.split(X, y, ts))
    assert len(splits) == 2


def test_embargo_zero_preserves_time_order():
    X, y, ts = _build_synthetic(300)
    cv = PurgedKFold(n_splits=5, embargo_bars=0)
    for train_idx, test_idx in cv.split(X, y, ts):
        assert train_idx.max() < test_idx.min()


def test_larger_embargo_removes_more_samples():
    X, y, ts = _build_synthetic(300)
    cv_small = PurgedKFold(n_splits=5, embargo_bars=1)
    cv_large = PurgedKFold(n_splits=5, embargo_bars=20)
    small = list(cv_small.split(X, y, ts))
    large = list(cv_large.split(X, y, ts))
    for (tr_s, _), (tr_l, _) in zip(small, large):
        assert len(tr_l) <= len(tr_s)


def test_non_divisible_n_samples_supported():
    X, y, ts = _build_synthetic(997)
    cv = PurgedKFold(n_splits=5, embargo_bars=5)
    splits = list(cv.split(X, y, ts))
    assert len(splits) >= 1
    for tr, te in splits:
        assert len(tr) > 0
        assert len(te) > 0


@pytest.mark.parametrize("n_samples", [101, 137, 223, 509, 777, 1001, 1234, 1501, 1999, 2503])
@pytest.mark.parametrize("embargo", [0, 1, 3, 5, 7, 10, 15, 20, 25, 30])
def test_purged_kfold_many_shapes_no_overlap(n_samples, embargo):
    X, y, ts = _build_synthetic(n_samples)
    cv = PurgedKFold(n_splits=5, embargo_bars=embargo)
    for train_idx, test_idx in cv.split(X, y, ts):
        assert len(set(train_idx).intersection(set(test_idx))) == 0
        assert train_idx.max() < test_idx.min()
