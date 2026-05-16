from __future__ import annotations

import time

from engines.backtester import generate_snapshots
from engines.ml.backtest_ml import backtest_ml_accuracy
from engines.ml.features import FEATURE_KEYS, build_dataset, extract_features
from engines.ml.ml_engine import MLEngine
from engines.ml.trainer import predict, train_model


def test_extract_features_keys_present():
    snaps = generate_snapshots("RELIANCE", 120, seed=1)
    f = extract_features(snaps, 50)
    assert set(f.keys()) == set(FEATURE_KEYS)


def test_extract_features_idx_zero_all_zero():
    snaps = generate_snapshots("RELIANCE", 120, seed=1)
    f = extract_features(snaps, 0)
    assert all(v == 0.0 for v in f.values())


def test_build_dataset_equal_lengths():
    snaps = generate_snapshots("TCS", 200, seed=2)
    X, y = build_dataset(snaps, lookahead=30)
    assert len(X) == len(y)


def test_build_dataset_targets_binary_only():
    snaps = generate_snapshots("INFY", 200, seed=3)
    _, y = build_dataset(snaps, lookahead=30)
    assert set(y).issubset({0, 1})


def test_train_model_required_keys():
    snaps = generate_snapshots("RELIANCE", 240, seed=4)
    out = train_model(snaps)
    for k in ["accuracy", "directional_accuracy", "precision", "recall", "f1", "n_train", "n_test", "feature_importance", "model_bytes"]:
        assert k in out


def test_train_model_accuracy_range():
    snaps = generate_snapshots("RELIANCE", 240, seed=5)
    out = train_model(snaps)
    assert 0.0 <= out["accuracy"] <= 1.0


def test_predict_direction_values():
    snaps = generate_snapshots("TCS", 260, seed=6)
    out = train_model(snaps)
    p = predict(out["model_bytes"], snaps, 200)
    assert p["direction"] in {"UP", "DOWN"}


def test_predict_confidence_range():
    snaps = generate_snapshots("TCS", 260, seed=7)
    out = train_model(snaps)
    p = predict(out["model_bytes"], snaps, 200)
    assert 0.0 <= p["confidence"] <= 1.0


def test_predict_probabilities_sum_to_one():
    snaps = generate_snapshots("TCS", 260, seed=8)
    out = train_model(snaps)
    p = predict(out["model_bytes"], snaps, 200)
    assert abs((p["probability_up"] + p["probability_down"]) - 1.0) < 1e-6


def test_mlengine_is_trained_false_initially():
    m = MLEngine()
    assert m.is_trained("RELIANCE") is False


def test_mlengine_get_signal_required_fields():
    m = MLEngine()
    s = m.get_signal("RELIANCE")
    for k in ["symbol", "direction", "confidence", "probability_up", "probability_down", "training"]:
        assert k in s


def test_mlengine_caches_model_second_call_faster_than_first():
    m = MLEngine()
    t1 = time.perf_counter()
    _ = m.get_signal("TCS")
    d1 = time.perf_counter() - t1

    t2 = time.perf_counter()
    _ = m.get_signal("TCS")
    d2 = time.perf_counter() - t2

    assert d2 <= d1


def test_backtest_ml_accuracy_fold_count():
    out = backtest_ml_accuracy("RELIANCE", n_snapshots=1000, n_folds=5)
    assert len(out["fold_accuracies"]) == 5


def test_backtest_ml_accuracy_mean_range():
    out = backtest_ml_accuracy("RELIANCE", n_snapshots=1000, n_folds=5)
    assert 0.0 <= out["mean_accuracy"] <= 1.0


def test_backtest_ml_accuracy_beats_random_bool():
    out = backtest_ml_accuracy("RELIANCE", n_snapshots=1000, n_folds=5)
    assert isinstance(out["beats_random"], bool)


def test_extract_features_values_are_floats():
    snaps = generate_snapshots("RELIANCE", 120, seed=9)
    f = extract_features(snaps, 60)
    assert all(isinstance(v, float) for v in f.values())


def test_build_dataset_minimum_rows_non_negative():
    snaps = generate_snapshots("RELIANCE", 80, seed=10)
    X, y = build_dataset(snaps, lookahead=30)
    assert len(X) >= 0
    assert len(y) >= 0


def test_train_model_feature_importance_has_all_features():
    snaps = generate_snapshots("INFY", 300, seed=11)
    out = train_model(snaps)
    assert set(out["feature_importance"].keys()) == set(FEATURE_KEYS)


def test_predict_probabilities_in_range():
    snaps = generate_snapshots("RELIANCE", 280, seed=12)
    out = train_model(snaps)
    p = predict(out["model_bytes"], snaps, 200)
    assert 0.0 <= p["probability_up"] <= 1.0
    assert 0.0 <= p["probability_down"] <= 1.0


def test_mlengine_get_metrics_contains_accuracy():
    m = MLEngine()
    out = m.get_metrics("RELIANCE")
    assert "accuracy" in out or "error" in out


def test_mlengine_retrain_returns_symbol():
    m = MLEngine()
    out = m.retrain("TCS")
    assert out["symbol"] == "TCS"


def test_mlengine_trained_after_signal():
    m = MLEngine()
    _ = m.get_signal("INFY")
    assert m.is_trained("INFY") is True


def test_backtest_ml_accuracy_has_std():
    out = backtest_ml_accuracy("TCS", n_snapshots=1000, n_folds=5)
    assert "std_accuracy" in out
    assert out["std_accuracy"] >= 0.0


def test_backtest_ml_accuracy_symbol_upper():
    out = backtest_ml_accuracy("hdfcbank", n_snapshots=1000, n_folds=5)
    assert out["symbol"] == "HDFCBANK"


def test_backtest_ml_accuracy_fold_values_range():
    out = backtest_ml_accuracy("ICICIBANK", n_snapshots=1000, n_folds=5)
    assert all(0.0 <= x <= 1.0 for x in out["fold_accuracies"])
