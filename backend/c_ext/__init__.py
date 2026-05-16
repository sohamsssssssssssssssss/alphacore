from __future__ import annotations

import ctypes
from ctypes import POINTER, Structure, byref, c_double, c_int
import os

from .build import build


class PriceLevel(Structure):
    _fields_ = [("price", c_double), ("quantity", c_double), ("active", c_int)]


MAX_LEVELS = 1024


class COrderBook(Structure):
    _fields_ = [
        ("bids", PriceLevel * MAX_LEVELS),
        ("asks", PriceLevel * MAX_LEVELS),
        ("bid_count", c_int),
        ("ask_count", c_int),
    ]


class IcebergResult(Structure):
    _fields_ = [("level_idx", c_int), ("confidence", c_double), ("detected", c_int)]


def _load_lib(path: str):
    if not os.path.exists(path):
        build()
    return ctypes.CDLL(path)


class FastOrderBook:
    def __init__(self):
        base = os.path.dirname(__file__)
        self.lib = _load_lib(os.path.join(base, "price_map.so"))
        self.ob = COrderBook()

        self.lib.ob_clear.argtypes = [POINTER(COrderBook)]
        self.lib.ob_insert_bid.argtypes = [POINTER(COrderBook), c_double, c_double]
        self.lib.ob_insert_ask.argtypes = [POINTER(COrderBook), c_double, c_double]
        self.lib.ob_best_bid.argtypes = [POINTER(COrderBook)]
        self.lib.ob_best_bid.restype = POINTER(PriceLevel)
        self.lib.ob_best_ask.argtypes = [POINTER(COrderBook)]
        self.lib.ob_best_ask.restype = POINTER(PriceLevel)
        self.lib.ob_mid_price.argtypes = [POINTER(COrderBook)]
        self.lib.ob_mid_price.restype = c_double
        self.lib.ob_spread_bps.argtypes = [POINTER(COrderBook)]
        self.lib.ob_spread_bps.restype = c_double

        self.clear()

    def insert_bid(self, price, qty):
        self.lib.ob_insert_bid(byref(self.ob), float(price), float(qty))

    def insert_ask(self, price, qty):
        self.lib.ob_insert_ask(byref(self.ob), float(price), float(qty))

    def best_bid(self):
        p = self.lib.ob_best_bid(byref(self.ob))
        if not p:
            return (0.0, 0.0)
        return (float(p.contents.price), float(p.contents.quantity))

    def best_ask(self):
        p = self.lib.ob_best_ask(byref(self.ob))
        if not p:
            return (0.0, 0.0)
        return (float(p.contents.price), float(p.contents.quantity))

    def mid_price(self) -> float:
        return float(self.lib.ob_mid_price(byref(self.ob)))

    def spread_bps(self) -> float:
        return float(self.lib.ob_spread_bps(byref(self.ob)))

    def clear(self):
        self.lib.ob_clear(byref(self.ob))


class FastDetector:
    def __init__(self):
        base = os.path.dirname(__file__)
        self.lib = _load_lib(os.path.join(base, "detection.so"))
        self.lib.iceberg_scan.argtypes = [POINTER(c_double), POINTER(c_double), c_int, c_double]
        self.lib.iceberg_scan.restype = IcebergResult
        self.lib.spoof_scan.argtypes = [
            POINTER(c_double), POINTER(c_double), POINTER(c_double), POINTER(c_double),
            c_int, c_double, c_double, c_double,
        ]
        self.lib.spoof_scan.restype = c_double

    def iceberg_scan(self, levels: list[tuple], threshold=0.7) -> dict:
        prices = (c_double * len(levels))(*[float(x[0]) for x in levels])
        qtys = (c_double * len(levels))(*[float(x[1]) for x in levels])
        out = self.lib.iceberg_scan(prices, qtys, len(levels), float(threshold))
        return {"level_idx": int(out.level_idx), "confidence": float(out.confidence), "detected": int(out.detected)}

    def spoof_scan(self, current, previous, mid_price, dist_bps=200, qty_thresh=10000) -> float:
        n = min(len(current), len(previous))
        cur_prices = (c_double * n)(*[float(x[0]) for x in current[:n]])
        cur_qtys = (c_double * n)(*[float(x[1]) for x in current[:n]])
        prev_prices = (c_double * n)(*[float(x[0]) for x in previous[:n]])
        prev_qtys = (c_double * n)(*[float(x[1]) for x in previous[:n]])
        return float(self.lib.spoof_scan(cur_prices, cur_qtys, prev_prices, prev_qtys, n, float(mid_price), float(dist_bps), float(qty_thresh)))


c_ext_available = True
try:
    _ = FastOrderBook()
    _ = FastDetector()
except Exception:
    c_ext_available = False
