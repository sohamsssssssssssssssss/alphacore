from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta

import pytest

from audit.audit_logger import AuditLogger


@pytest.fixture
def logger(tmp_path):
    db_path = tmp_path / "audit.db"
    return AuditLogger(db_url=f"sqlite:///{db_path}")


def _today_ist_str() -> str:
    now_utc = datetime.now(UTC)
    ist = now_utc + timedelta(hours=5, minutes=30)
    return ist.strftime("%Y-%m-%d")


def test_append_returns_incrementing_seq(logger):
    s1 = logger.append({"event_type": "ORDER_SUBMIT", "symbol": "RELIANCE"})
    s2 = logger.append({"event_type": "ORDER_ACK", "symbol": "RELIANCE"})
    assert s2 == s1 + 1


def test_count_grows_monotonically(logger):
    c0 = logger.count()
    logger.append({"event_type": "SESSION_START", "symbol": "NIFTY"})
    c1 = logger.count()
    logger.append({"event_type": "SESSION_END", "symbol": "NIFTY"})
    c2 = logger.count()
    assert c1 > c0
    assert c2 > c1


def test_invalid_event_type_raises(logger):
    with pytest.raises(ValueError):
        logger.append({"event_type": "BAD_EVENT", "symbol": "INFY"})


def test_unknown_side_coerced_to_na(logger):
    logger.append({"event_type": "ORDER_SUBMIT", "symbol": "INFY", "side": "WHATEVER"})
    today = _today_ist_str()
    rows = logger.replay_session(today)
    assert rows[-1]["side"] == "N/A"


def test_extra_fields_stored_and_retrievable(logger):
    logger.append({"event_type": "STRATEGY_SIGNAL", "symbol": "TCS", "alpha": 0.42, "note": "x"})
    today = _today_ist_str()
    rows = logger.replay_session(today)
    assert rows[-1]["extra"]["alpha"] == 0.42
    assert rows[-1]["extra"]["note"] == "x"


def test_export_csv_creates_file_with_correct_columns_and_ist(tmp_path, logger):
    logger.append({"event_type": "ORDER_ACK", "symbol": "SBIN", "qty": 10, "price": 100.5})
    day = _today_ist_str()
    out = tmp_path / "audit.csv"

    n = logger.export_csv(day, day, str(out))
    assert n >= 1
    assert out.exists()

    with out.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row = next(iter(reader))
        assert reader.fieldnames == ["seq", "logged_at", "event_type", "symbol", "side", "qty", "price", "strategy_id", "order_id", "extra"]
        assert row["logged_at"].endswith("IST")


def test_export_empty_date_range_returns_zero(tmp_path, logger):
    out = tmp_path / "empty.csv"
    n = logger.export_csv("1999-01-01", "1999-01-01", str(out))
    assert n == 0


def test_replay_session_returns_ordered_by_seq(logger):
    s1 = logger.append({"event_type": "ORDER_SUBMIT", "symbol": "RELIANCE"})
    s2 = logger.append({"event_type": "ORDER_ACK", "symbol": "RELIANCE"})
    s3 = logger.append({"event_type": "FULL_FILL", "symbol": "RELIANCE"})
    rows = logger.replay_session(_today_ist_str())
    seqs = [r["seq"] for r in rows if r["seq"] in {s1, s2, s3}]
    assert seqs == sorted(seqs)


def test_replay_is_deterministic(logger):
    logger.append({"event_type": "ORDER_SUBMIT", "symbol": "RELIANCE"})
    day = _today_ist_str()
    r1 = logger.replay_session(day)
    r2 = logger.replay_session(day)
    assert r1 == r2


def test_replay_session_isolation(logger):
    today = _today_ist_str()
    logger.append({"event_type": "ORDER_SUBMIT", "symbol": "AAA"})
    rows_today = logger.replay_session(today)
    rows_old = logger.replay_session("1999-01-01")
    assert len(rows_today) >= 1
    assert rows_old == []


def test_append_only_contract_no_mutation_methods(logger):
    for name in ("update", "delete", "patch", "modify"):
        assert not hasattr(logger, name)


def test_high_precision_price_qty_round_trip(logger):
    px = 1234.567890123
    qty = 0.123456789
    logger.append({"event_type": "PAPER_TRADE", "symbol": "HDFCBANK", "price": px, "qty": qty})
    row = logger.replay_session(_today_ist_str())[-1]
    assert abs(float(row["price"]) - px) < 1e-12
    assert abs(float(row["qty"]) - qty) < 1e-12
