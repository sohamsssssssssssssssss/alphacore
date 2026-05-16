from __future__ import annotations

import pickle

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score

from engines.backtester import Snapshot
from engines.ml.features import FEATURE_KEYS, build_dataset, extract_features


def train_model(snapshots: list[Snapshot], lookahead: int = 30) -> dict:
    X, y = build_dataset(snapshots, lookahead)
    if len(X) < 50:
        return {"error": "insufficient data"}

    split = int(len(X) * 0.8)
    if split <= 0 or split >= len(X):
        return {"error": "insufficient data"}

    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    clf = RandomForestClassifier(n_estimators=100, random_state=42, max_depth=6, n_jobs=-1)
    clf.fit(X_train, y_train)

    pred = clf.predict(X_test)
    acc = float(accuracy_score(y_test, pred))
    prec = float(precision_score(y_test, pred, zero_division=0))
    rec = float(recall_score(y_test, pred, zero_division=0))
    f1 = float(f1_score(y_test, pred, zero_division=0))

    feature_importance = {k: float(v) for k, v in zip(FEATURE_KEYS, clf.feature_importances_)}

    return {
        "accuracy": acc,
        "directional_accuracy": acc,
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "n_train": len(X_train),
        "n_test": len(X_test),
        "feature_importance": feature_importance,
        "model_bytes": pickle.dumps(clf),
    }


def predict(model_bytes: bytes, snapshots: list[Snapshot], idx: int) -> dict:
    clf = pickle.loads(model_bytes)
    feats = extract_features(snapshots, idx)
    x = [[float(feats[k]) for k in FEATURE_KEYS]]
    proba = clf.predict_proba(x)[0]
    p_down = float(proba[0])
    p_up = float(proba[1]) if len(proba) > 1 else 0.0
    direction = "UP" if p_up > 0.5 else "DOWN"
    return {
        "direction": direction,
        "confidence": float(max(p_up, p_down)),
        "probability_up": p_up,
        "probability_down": p_down,
    }
