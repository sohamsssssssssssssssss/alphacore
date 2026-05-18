from __future__ import annotations

import queue
import sys
import threading
import time

import pytest

sys.path.insert(0, "/tmp/alphacore_build")
sys_mod = pytest.importorskip("alphacore_cpp")
_ = sys_mod

from tests.cpp.replication_mock import BackupNode, HeartbeatMonitor, LeaderLease, PrimaryNode


class TestReplication:
    def test_backup_receives_log_entry(self):
        q: queue.Queue = queue.Queue()
        lease = LeaderLease()
        primary = PrimaryNode("primary", q, lease)
        backup = BackupNode("backup", q, lease)
        try:
            got = threading.Event()

            def waiter():
                t0 = time.perf_counter()
                while time.perf_counter() - t0 < 1.0:
                    if backup.applied:
                        got.set()
                        return
                    time.sleep(0.005)

            th = threading.Thread(target=waiter)
            th.start()
            primary.submit_order("B", 100.0, 10)
            th.join(timeout=1.0)
            assert got.is_set()
        finally:
            backup.stop()

    def test_backup_state_matches_primary(self):
        q: queue.Queue = queue.Queue()
        lease = LeaderLease()
        primary = PrimaryNode("primary", q, lease)
        backup = BackupNode("backup", q, lease)
        try:
            for i in range(100):
                side = "B" if i % 2 == 0 else "S"
                px = 100.0 + (i % 10) * 0.1
                primary.submit_order(side, px, 1)
            t0 = time.perf_counter()
            while len(backup.applied) < 100 and (time.perf_counter() - t0) < 1.0:
                time.sleep(0.005)
            assert backup.best_bid == primary.best_bid
            assert backup.best_ask == primary.best_ask
        finally:
            backup.stop()

    def test_backup_promotion_on_missed_heartbeats(self):
        q: queue.Queue = queue.Queue()
        lease = LeaderLease()
        _primary = PrimaryNode("primary", q, lease)
        backup = BackupNode("backup", q, lease)
        promoted = threading.Event()
        mon = HeartbeatMonitor(interval_s=0.1, max_miss=3, on_timeout=lambda: (backup.promote(), promoted.set()))
        try:
            assert promoted.wait(timeout=0.5)
            assert backup.is_primary is True
            out = backup.submit_order("B", 101.0, 5)
            assert out["qty"] == 5
        finally:
            mon.stop()
            backup.stop()

    def test_split_brain_prevention(self):
        q: queue.Queue = queue.Queue()
        lease = LeaderLease()
        primary = PrimaryNode("primary", q, lease)
        backup = BackupNode("backup", q, lease)
        try:
            stale_epoch = primary.epoch
            backup.promote()
            primary.epoch = stale_epoch
            with pytest.raises(RuntimeError):
                primary.submit_order("B", 100.0, 1)
        finally:
            backup.stop()

    def test_replication_lag_under_load(self):
        q: queue.Queue = queue.Queue()
        lease = LeaderLease()
        primary = PrimaryNode("primary", q, lease)
        backup = BackupNode("backup", q, lease)
        try:
            send_ts = {}
            for i in range(1000):
                e = primary.submit_order("B" if i % 2 == 0 else "S", 100.0 + (i % 5) * 0.1, 1)
                send_ts[e["seq"]] = time.perf_counter()

            t0 = time.perf_counter()
            while len(backup.applied) < 1000 and (time.perf_counter() - t0) < 2.0:
                time.sleep(0.001)
            assert len(backup.applied) == 1000

            max_lag_ms = 0.0
            now = time.perf_counter()
            for e in backup.applied:
                max_lag_ms = max(max_lag_ms, (now - send_ts[e["seq"]]) * 1000.0)
            print(f"max replication lag ms={max_lag_ms:.3f}")
        finally:
            backup.stop()

    def test_primary_recovery_after_restart(self):
        q: queue.Queue = queue.Queue()
        lease = LeaderLease()
        primary = PrimaryNode("primary", q, lease)
        backup = BackupNode("backup", q, lease)
        try:
            for i in range(500):
                primary.submit_order("B", 100.0 + (i % 3) * 0.1, 1)
            t0 = time.perf_counter()
            while len(backup.applied) < 500 and (time.perf_counter() - t0) < 1.0:
                time.sleep(0.002)

            backup.promote()
            for i in range(100):
                backup.submit_order("S", 101.0 + (i % 2) * 0.1, 1)

            recovered = BackupNode("primary-restarted", queue.Queue(), lease)
            try:
                for e in backup.applied[-100:]:
                    recovered.apply_entry(e)
                assert len(recovered.applied) >= 100
            finally:
                recovered.stop()
        finally:
            backup.stop()

    def test_heartbeat_monitor_fires_on_timeout(self):
        fired = threading.Event()
        mon = HeartbeatMonitor(interval_s=0.1, max_miss=3, on_timeout=lambda: fired.set())
        try:
            assert fired.wait(timeout=0.4)
        finally:
            mon.stop()
