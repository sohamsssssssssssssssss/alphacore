from __future__ import annotations

import queue
import threading
import time


class LeaderLease:
    def __init__(self):
        self._lock = threading.Lock()
        self._epoch = 1
        self._leader = "primary"

    def grant(self, leader: str) -> int:
        with self._lock:
            self._epoch += 1
            self._leader = leader
            return self._epoch

    def validate(self, leader: str, epoch: int) -> None:
        with self._lock:
            if leader != self._leader or epoch != self._epoch:
                raise RuntimeError("stale leader fenced by epoch")


class PrimaryNode:
    def __init__(self, name: str, out_q: queue.Queue, lease: LeaderLease):
        self.name = name
        self.out_q = out_q
        self.lease = lease
        self.is_primary = True
        self.epoch = lease.grant(name)
        self.log: list[dict] = []
        self.best_bid = 0.0
        self.best_ask = float("inf")
        self._seq = 0

    def submit_order(self, side: str, price: float, qty: int) -> dict:
        self.lease.validate(self.name, self.epoch)
        self._seq += 1
        entry = {"seq": self._seq, "side": side, "price": float(price), "qty": int(qty)}
        self.log.append(entry)
        if side == "B":
            self.best_bid = max(self.best_bid, float(price))
        else:
            self.best_ask = min(self.best_ask, float(price))
        self.out_q.put(entry)
        return entry


class BackupNode:
    def __init__(self, name: str, in_q: queue.Queue, lease: LeaderLease):
        self.name = name
        self.in_q = in_q
        self.lease = lease
        self.is_primary = False
        self.epoch = 0
        self.applied: list[dict] = []
        self.best_bid = 0.0
        self.best_ask = float("inf")
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                entry = self.in_q.get(timeout=0.05)
            except queue.Empty:
                continue
            self.apply_entry(entry)

    def apply_entry(self, entry: dict) -> None:
        self.applied.append(entry)
        if entry["side"] == "B":
            self.best_bid = max(self.best_bid, float(entry["price"]))
        else:
            self.best_ask = min(self.best_ask, float(entry["price"]))

    def promote(self) -> None:
        self.is_primary = True
        self.epoch = self.lease.grant(self.name)

    def submit_order(self, side: str, price: float, qty: int) -> dict:
        if not self.is_primary:
            raise RuntimeError("backup is not primary")
        self.lease.validate(self.name, self.epoch)
        entry = {"seq": len(self.applied) + 1, "side": side, "price": float(price), "qty": int(qty)}
        self.apply_entry(entry)
        return entry

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)


class HeartbeatMonitor:
    def __init__(self, interval_s: float, max_miss: int, on_timeout):
        self.interval_s = float(interval_s)
        self.max_miss = int(max_miss)
        self.on_timeout = on_timeout
        self._last = time.perf_counter()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def beat(self) -> None:
        self._last = time.perf_counter()

    def _run(self):
        while not self._stop.is_set():
            time.sleep(self.interval_s)
            miss = (time.perf_counter() - self._last) / self.interval_s
            if miss >= self.max_miss:
                self.on_timeout()
                return

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=1.0)
