from __future__ import annotations

import math
from collections import deque

import numpy as np
import pandas as pd

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

FEATURE42_KEYS = [
    "mid_price",
    "micro_price",
    "spread_abs",
    "spread_bps",
    "price_mom_1m",
    "price_mom_5m",
    "price_mom_15m",
    "vwap_deviation",
    "total_bid_vol",
    "total_ask_vol",
    "bid_ask_ratio",
    "depth_imbalance",
    "bid_slope",
    "ask_slope",
    "weighted_bid_price",
    "weighted_ask_price",
    "ofi",
    "trade_flow_imbalance",
    "cancel_rate_bid",
    "cancel_rate_ask",
    "replenishment_rate",
    "trade_to_cancel_ratio",
    "level_decay_speed",
    "amihud_illiquidity",
    "roll_spread",
    "corwin_schultz_spread",
    "realized_vol_1m",
    "realized_vol_5m",
    "volume_surge_ratio",
    "abnormal_order_arrival_rate",
    "realized_skew",
    "iceberg_confidence",
    "iceberg_hidden_vol",
    "spoof_score",
    "spoof_severity_encoded",
    "iceberg_count_bid",
    "iceberg_count_ask",
    "spoof_reversal_flag",
    "rel_spread_vs_sector",
    "rel_vol_vs_sector",
    "beta_to_nifty",
    "sector_correlation",
]


class OrderBookFeatureEngine:
    def __init__(self, use_cpp: bool = True):
        self.use_cpp = bool(use_cpp)
        self._cpp = None
        if self.use_cpp:
            try:
                import alphacore_cpp as _cpp  # type: ignore
                self._cpp = _cpp
            except Exception:
                self._cpp = None

        self._mid_hist: deque[float] = deque(maxlen=1024)
        self._vol_hist: deque[float] = deque(maxlen=1024)
        self._ret_hist: deque[float] = deque(maxlen=1024)
        self._spread_hist: deque[float] = deque(maxlen=1024)
        self._ofi_hist: deque[float] = deque(maxlen=1024)
        self._arrival_hist: deque[int] = deque(maxlen=1024)
        self._last_ts_ns: int | None = None
        self._iceberg_bid_count = 0
        self._iceberg_ask_count = 0

    @staticmethod
    def _safe_div(a: float, b: float) -> float:
        return 0.0 if b == 0.0 else float(a / b)

    @staticmethod
    def _std(vals: list[float]) -> float:
        if len(vals) < 2:
            return 0.0
        return float(np.std(np.asarray(vals, dtype=float)))

    @staticmethod
    def _skew(vals: list[float]) -> float:
        if len(vals) < 3:
            return 0.0
        arr = np.asarray(vals, dtype=float)
        mu = float(np.mean(arr))
        sd = float(np.std(arr))
        if sd == 0.0:
            return 0.0
        return float(np.mean(((arr - mu) / sd) ** 3))

    def _mom(self, lookback: int, cur: float) -> float:
        if len(self._mid_hist) <= lookback:
            return 0.0
        prev = list(self._mid_hist)[-1 - lookback]
        return self._safe_div(cur - prev, prev)

    def _realized_vol(self, n: int) -> float:
        rets = list(self._ret_hist)[-n:] if len(self._ret_hist) >= 1 else []
        return self._std(rets)

    def compute(self, snapshot: dict) -> dict:
        bid_prices = [float(x) for x in snapshot.get("bid_prices", [0, 0, 0, 0, 0])]
        ask_prices = [float(x) for x in snapshot.get("ask_prices", [0, 0, 0, 0, 0])]
        bid_qtys = [float(x) for x in snapshot.get("bid_qtys", [0, 0, 0, 0, 0])]
        ask_qtys = [float(x) for x in snapshot.get("ask_qtys", [0, 0, 0, 0, 0])]
        last_price = float(snapshot.get("last_price", 0.0))
        volume = float(snapshot.get("volume", 0.0))
        ts_ns = int(snapshot.get("timestamp_ns", 0))
        iceberg_conf = float(snapshot.get("iceberg_confidence", 0.0))
        iceberg_side = str(snapshot.get("iceberg_side", "")).upper()
        spoof_score = float(snapshot.get("spoof_score", 0.0))
        spoof_severity = str(snapshot.get("spoof_severity", "LOW")).upper()
        market_returns = snapshot.get("market_returns", [])
        market_returns_arr = np.asarray(market_returns, dtype=float) if len(market_returns) else np.asarray([], dtype=float)

        best_bid = bid_prices[0] if bid_prices else 0.0
        best_ask = ask_prices[0] if ask_prices else best_bid
        mid = (best_bid + best_ask) / 2.0
        spread_abs = max(0.0, best_ask - best_bid)
        spread_bps = self._safe_div(spread_abs, mid) * 10000.0 if mid > 0 else 0.0
        total_bid = float(sum(bid_qtys))
        total_ask = float(sum(ask_qtys))
        bid_ask_ratio = self._safe_div(total_bid, total_ask)
        depth_imb = self._safe_div(total_bid - total_ask, total_bid + total_ask)
        depth_imb = float(max(-1.0, min(1.0, depth_imb)))
        micro_price = self._safe_div(best_ask * (bid_qtys[0] if bid_qtys else 0.0) + best_bid * (ask_qtys[0] if ask_qtys else 0.0),
                                     (bid_qtys[0] if bid_qtys else 0.0) + (ask_qtys[0] if ask_qtys else 0.0))

        weighted_bid = self._safe_div(sum(p * q for p, q in zip(bid_prices, bid_qtys)), total_bid)
        weighted_ask = self._safe_div(sum(p * q for p, q in zip(ask_prices, ask_qtys)), total_ask)
        bid_slope = (bid_prices[0] - bid_prices[-1]) / max(1, len(bid_prices) - 1) if len(bid_prices) > 1 else 0.0
        ask_slope = (ask_prices[-1] - ask_prices[0]) / max(1, len(ask_prices) - 1) if len(ask_prices) > 1 else 0.0

        vwap = self._safe_div(sum((p * q) for p, q in zip(bid_prices + ask_prices, bid_qtys + ask_qtys)),
                              sum(bid_qtys + ask_qtys))
        vwap_dev = self._safe_div(last_price - vwap, vwap)

        if self._mid_hist:
            prev_mid = self._mid_hist[-1]
            ret = self._safe_div(mid - prev_mid, prev_mid)
        else:
            ret = 0.0

        self._mid_hist.append(mid)
        self._vol_hist.append(volume)
        self._ret_hist.append(ret)
        self._spread_hist.append(spread_bps)

        ofi = depth_imb
        self._ofi_hist.append(ofi)
        trade_flow_imb = self._safe_div((volume - (self._vol_hist[-2] if len(self._vol_hist) > 1 else 0.0)), max(1.0, volume))
        cancel_rate_bid = float(max(0.0, -min(0.0, (bid_qtys[0] - (bid_qtys[1] if len(bid_qtys) > 1 else bid_qtys[0])))))
        cancel_rate_ask = float(max(0.0, -min(0.0, (ask_qtys[0] - (ask_qtys[1] if len(ask_qtys) > 1 else ask_qtys[0])))))
        replenishment_rate = float(max(0.0, (total_bid + total_ask) / max(1.0, volume)))
        trade_to_cancel_ratio = self._safe_div(volume, cancel_rate_bid + cancel_rate_ask + 1e-9)
        level_decay_speed = self._safe_div((bid_qtys[0] + ask_qtys[0]), (total_bid + total_ask))

        amihud = self._safe_div(abs(ret), max(volume, 1.0))
        roll_spread = 2.0 * self._std(list(self._ret_hist)[-20:])
        corwin_schultz = math.sqrt(max(0.0, spread_bps / 10000.0))
        rv1 = self._realized_vol(20)
        rv5 = self._realized_vol(100)
        vol_ma = float(np.mean(list(self._vol_hist)[-20:])) if self._vol_hist else volume
        volume_surge = self._safe_div(volume, vol_ma) - 1.0 if vol_ma > 0 else 0.0
        self._arrival_hist.append(1 if self._last_ts_ns is None or ts_ns > self._last_ts_ns else 0)
        abnormal_arrival = self._safe_div(sum(list(self._arrival_hist)[-20:]), 20.0)
        realized_skew = self._skew(list(self._ret_hist)[-50:])
        self._last_ts_ns = ts_ns

        iceberg_hidden = iceberg_conf * volume
        spoof_sev_map = {"LOW": 0.0, "MEDIUM": 1.0, "HIGH": 2.0, "CRITICAL": 3.0}
        spoof_sev_encoded = spoof_sev_map.get(spoof_severity, 0.0)
        if iceberg_side == "BID":
            self._iceberg_bid_count += 1
        elif iceberg_side == "ASK":
            self._iceberg_ask_count += 1
        spoof_reversal_flag = 1.0 if spoof_score > 50.0 and ret > 0 else 0.0
        flow_regime = 1.0 if ofi > 0.2 else (-1.0 if ofi < -0.2 else 0.0)

        sector_spread = float(snapshot.get("sector_spread_bps", spread_bps if spread_bps > 0 else 1.0))
        sector_vol = float(snapshot.get("sector_realized_vol", rv5 if rv5 > 0 else 1.0))
        rel_spread = self._safe_div(spread_bps, sector_spread)
        rel_vol = self._safe_div(rv5, sector_vol)
        beta_to_nifty = self._safe_div(float(np.cov(np.asarray(list(self._ret_hist)[-len(market_returns_arr):], dtype=float),
                                                     market_returns_arr)[0, 1]) if len(market_returns_arr) > 1 and len(self._ret_hist) >= len(market_returns_arr) else 0.0,
                                       float(np.var(market_returns_arr)) if len(market_returns_arr) > 1 else 0.0)
        sector_corr = float(np.corrcoef(np.asarray(list(self._ret_hist)[-len(market_returns_arr):], dtype=float), market_returns_arr)[0, 1]) \
            if len(market_returns_arr) > 2 and len(self._ret_hist) >= len(market_returns_arr) and np.std(market_returns_arr) > 0 else 0.0

        out = {
            "mid_price": float(mid),
            "micro_price": float(micro_price),
            "spread_abs": float(spread_abs),
            "spread_bps": float(spread_bps),
            "price_mom_1m": float(self._mom(1, mid)),
            "price_mom_5m": float(self._mom(5, mid)),
            "price_mom_15m": float(self._mom(15, mid)),
            "vwap_deviation": float(vwap_dev),
            "total_bid_vol": float(total_bid),
            "total_ask_vol": float(total_ask),
            "bid_ask_ratio": float(bid_ask_ratio),
            "depth_imbalance": float(depth_imb),
            "bid_slope": float(bid_slope),
            "ask_slope": float(ask_slope),
            "weighted_bid_price": float(weighted_bid),
            "weighted_ask_price": float(weighted_ask),
            "ofi": float(ofi),
            "trade_flow_imbalance": float(trade_flow_imb),
            "cancel_rate_bid": float(cancel_rate_bid),
            "cancel_rate_ask": float(cancel_rate_ask),
            "replenishment_rate": float(replenishment_rate),
            "trade_to_cancel_ratio": float(trade_to_cancel_ratio),
            "level_decay_speed": float(level_decay_speed),
            "amihud_illiquidity": float(amihud),
            "roll_spread": float(roll_spread),
            "corwin_schultz_spread": float(corwin_schultz),
            "realized_vol_1m": float(rv1),
            "realized_vol_5m": float(rv5),
            "volume_surge_ratio": float(volume_surge),
            "abnormal_order_arrival_rate": float(abnormal_arrival),
            "realized_skew": float(realized_skew),
            "iceberg_confidence": float(iceberg_conf),
            "iceberg_hidden_vol": float(iceberg_hidden),
            "spoof_score": float(spoof_score),
            "spoof_severity_encoded": float(spoof_sev_encoded),
            "iceberg_count_bid": float(self._iceberg_bid_count),
            "iceberg_count_ask": float(self._iceberg_ask_count),
            "spoof_reversal_flag": float(spoof_reversal_flag),
            "flow_regime_encoded": float(flow_regime),
            "rel_spread_vs_sector": float(rel_spread),
            "rel_vol_vs_sector": float(rel_vol),
            "beta_to_nifty": float(beta_to_nifty),
            "sector_correlation": float(sector_corr),
        }
        return {k: out[k] for k in FEATURE42_KEYS}

    def compute_batch(self, snapshots: list[dict]) -> pd.DataFrame:
        rows = [self.compute(s) for s in snapshots]
        return pd.DataFrame(rows, columns=FEATURE42_KEYS)


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
