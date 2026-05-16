from __future__ import annotations

import timeit

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from c_ext import FastDetector, FastOrderBook, c_ext_available


def py_mid_price(levels):
    best_bid = max(levels["bids"], key=lambda x: x[0])
    best_ask = min(levels["asks"], key=lambda x: x[0])
    return (best_bid[0] + best_ask[0]) / 2.0


def py_iceberg(levels, threshold=0.7):
    qtys = [q for _p, q in levels]
    total = sum(qtys)
    if total <= 0:
        return {"detected": 0, "level_idx": -1, "confidence": 0.0}
    for i, q in enumerate(qtys):
        c = q / total
        if c > threshold:
            return {"detected": 1, "level_idx": i, "confidence": c}
    return {"detected": 0, "level_idx": -1, "confidence": 0.0}


def run():
    if not c_ext_available:
        print("C extension unavailable; build failed or gcc missing")
        return

    levels = {
        "bids": [(100 - i * 0.1, 1000 + i * 5) for i in range(50)],
        "asks": [(100 + i * 0.1, 900 + i * 4) for i in range(50)],
    }
    detector_levels = [(100 - i * 0.1, 1000 + i * 5) for i in range(50)]
    prev = [(100 - i * 0.1, 12000 if i == 0 else 1000 + i * 3) for i in range(20)]
    cur = [(100 - i * 0.1, 0 if i == 0 else 1000 + i * 2) for i in range(20)]

    fob = FastOrderBook()
    fd = FastDetector()

    def py_book_call():
        return py_mid_price(levels)

    def c_book_call():
        fob.clear()
        for p, q in levels["bids"]:
            fob.insert_bid(p, q)
        for p, q in levels["asks"]:
            fob.insert_ask(p, q)
        return fob.mid_price()

    def py_det_call():
        return py_iceberg(detector_levels)

    def c_det_call():
        return fd.iceberg_scan(detector_levels, threshold=0.7)

    py_book = timeit.timeit(py_book_call, number=10000)
    c_book = timeit.timeit(c_book_call, number=10000)
    py_det = timeit.timeit(py_det_call, number=10000)
    c_det = timeit.timeit(c_det_call, number=10000)

    print(f"Python order book (mid_price): {py_book * 1000:.3f} ms avg")
    print(f"C ext order book (mid_price):  {c_book * 1000:.3f} ms avg")
    print(f"Speedup: {py_book / c_book:.2f}x")
    print(f"Python iceberg scan: {py_det * 1000:.3f} ms avg")
    print(f"C ext iceberg scan:  {c_det * 1000:.3f} ms avg")
    print(f"Speedup: {py_det / c_det:.2f}x")

    spoof_score = fd.spoof_scan(cur, prev, mid_price=100.0)
    print(f"Sample spoof score: {spoof_score:.4f}")


if __name__ == "__main__":
    run()
