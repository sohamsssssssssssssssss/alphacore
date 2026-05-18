from __future__ import annotations

import csv

from paper_digest import DailyDigest, DigestEntry


def _entry(day: int, net: float = 100.0, sharpe: float = 1.0) -> DigestEntry:
    return DigestEntry(
        date=f"2026-01-{day:02d}",
        gross_pnl=net + 10.0,
        net_pnl=net,
        total_trades=10,
        win_rate=0.6,
        max_drawdown=1.2,
        risk_violations=0,
        regime_distribution={"trending": 0.4, "mean_reverting": 0.6},
        signal_accuracy=0.55,
        sharpe_today=sharpe,
    )


def test_digest_entry_dataclass():
    d = _entry(1)
    assert d.date == "2026-01-01"
    assert d.net_pnl == 100.0


def test_save_creates_csv(tmp_path):
    csv_path = tmp_path / "digest.csv"
    dg = DailyDigest(audit_db=str(tmp_path / "audit.db"), digest_csv=str(csv_path))
    dg.save(_entry(1))
    assert csv_path.exists()
    with csv_path.open("r", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 2


def test_save_appends(tmp_path):
    csv_path = tmp_path / "digest.csv"
    dg = DailyDigest(audit_db=str(tmp_path / "audit.db"), digest_csv=str(csv_path))
    dg.save(_entry(1))
    dg.save(_entry(2))
    with csv_path.open("r", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 3


def test_load_history_empty(tmp_path):
    dg = DailyDigest(audit_db=str(tmp_path / "audit.db"), digest_csv=str(tmp_path / "none.csv"))
    assert dg.load_history() == []


def test_load_history_round_trips(tmp_path):
    csv_path = tmp_path / "digest.csv"
    dg = DailyDigest(audit_db=str(tmp_path / "audit.db"), digest_csv=str(csv_path))
    dg.save(_entry(1, net=100.0))
    dg.save(_entry(2, net=200.0))
    dg.save(_entry(3, net=300.0))
    h = dg.load_history()
    assert len(h) == 3
    assert h[1].net_pnl == 200.0


def test_check_graduation_false_not_enough_days(tmp_path):
    csv_path = tmp_path / "digest.csv"
    dg = DailyDigest(audit_db=str(tmp_path / "audit.db"), digest_csv=str(csv_path))
    for i in range(1, 6):
        dg.save(_entry(i, net=100.0, sharpe=1.0))
    assert dg.check_graduation() is False


def test_check_graduation_false_negative_pnl(tmp_path):
    csv_path = tmp_path / "digest.csv"
    dg = DailyDigest(audit_db=str(tmp_path / "audit.db"), digest_csv=str(csv_path))
    for i in range(1, 61):
        dg.save(_entry(i, net=-100.0, sharpe=1.0))
    assert dg.check_graduation() is False


def test_check_graduation_true(tmp_path):
    csv_path = tmp_path / "digest.csv"
    dg = DailyDigest(audit_db=str(tmp_path / "audit.db"), digest_csv=str(csv_path))
    for i in range(1, 61):
        dg.save(_entry(i, net=500.0, sharpe=1.0))
    assert dg.check_graduation() is True


def test_print_dashboard_no_crash(tmp_path):
    dg = DailyDigest(audit_db=str(tmp_path / "audit.db"), digest_csv=str(tmp_path / "digest.csv"))
    dg.print_dashboard()


def test_sharpe_zero_guard(tmp_path):
    csv_path = tmp_path / "digest.csv"
    dg = DailyDigest(audit_db=str(tmp_path / "audit.db"), digest_csv=str(csv_path))
    dg.save(_entry(1, net=0.0, sharpe=0.0))
    assert dg.check_graduation() is False
