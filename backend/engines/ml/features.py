from __future__ import annotations

import math

from engines.backtester import Snapshot


FEATURE_KEYS = [
    "mid_price_change_1m",
    "mid_price_change_5m",
    "spread_bps",
    "spread_ma5",
    "bid_ask_ratio",
    "ofi",
    "ofi_ma5",
    "depth_imbalance",
    "momentum_1m",
    "momentum_5m",
    "z_score",
    "vol_5m",
    "vol_15m",
    "spread_vol",
]


def _safe_pct(cur: float, prev: float) -> float:
    if prev == 0:
        return 0.0
    return (cur - prev) / prev


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    return math.sqrt(sum((x - m) ** 2 for x in values) / len(values))


def extract_features(snapshots: list[Snapshot], idx: int) -> dict:
    if idx <= 0 or idx >= len(snapshots):
        return {k: 0.0 for k in FEATURE_KEYS}

    cur = snapshots[idx]
    mids = [s.mid_price for s in snapshots]
    spreads = [s.spread_bps for s in snapshots]

    mid_1m = _safe_pct(cur.mid_price, mids[idx - 1]) if idx >= 1 else 0.0
    mid_5m = _safe_pct(cur.mid_price, mids[idx - 5]) if idx >= 5 else 0.0

    spread_ma5 = sum(spreads[max(0, idx - 4): idx + 1]) / len(spreads[max(0, idx - 4): idx + 1]) if idx >= 0 else 0.0

    ask_vol = cur.ask_volume if cur.ask_volume > 0 else 1e-9
    bid_ask_ratio = max(0.1, min(10.0, cur.bid_volume / ask_vol))

    denom = cur.bid_volume + cur.ask_volume
    ofi = (cur.bid_volume - cur.ask_volume) / denom if denom > 0 else 0.0
    ofis = []
    for s in snapshots[max(0, idx - 4): idx + 1]:
        d = s.bid_volume + s.ask_volume
        ofis.append((s.bid_volume - s.ask_volume) / d if d > 0 else 0.0)
    ofi_ma5 = sum(ofis) / len(ofis) if ofis else 0.0

    depth_imbalance = ofi

    momentum_1m = _safe_pct(cur.mid_price, mids[idx - 1]) * 10000.0 if idx >= 1 else 0.0
    momentum_5m = _safe_pct(cur.mid_price, mids[idx - 5]) * 10000.0 if idx >= 5 else 0.0

    z_window = mids[max(0, idx - 19): idx + 1]
    if len(z_window) < 2:
        z_score = 0.0
    else:
        mean = sum(z_window) / len(z_window)
        std = _std(z_window)
        z_score = ((cur.mid_price - mean) / std) if std > 0 else 0.0

    vol_5m = _std(mids[max(0, idx - 4): idx + 1])
    vol_15m = _std(mids[max(0, idx - 14): idx + 1])
    spread_vol = _std(spreads[max(0, idx - 4): idx + 1])

    out = {
        "mid_price_change_1m": float(mid_1m),
        "mid_price_change_5m": float(mid_5m),
        "spread_bps": float(cur.spread_bps),
        "spread_ma5": float(spread_ma5),
        "bid_ask_ratio": float(bid_ask_ratio),
        "ofi": float(ofi),
        "ofi_ma5": float(ofi_ma5),
        "depth_imbalance": float(depth_imbalance),
        "momentum_1m": float(momentum_1m),
        "momentum_5m": float(momentum_5m),
        "z_score": float(z_score),
        "vol_5m": float(vol_5m),
        "vol_15m": float(vol_15m),
        "spread_vol": float(spread_vol),
    }
    return out


def build_dataset(snapshots: list[Snapshot], lookahead: int = 30) -> tuple[list, list]:
    X: list[list[float]] = []
    y: list[int] = []
    for idx in range(15, len(snapshots) - lookahead):
        feats = extract_features(snapshots, idx)
        X.append([float(feats[k]) for k in FEATURE_KEYS])
        future_mid = snapshots[idx + lookahead].mid_price
        current_mid = snapshots[idx].mid_price
        y.append(1 if future_mid > current_mid else 0)
    return X, y
