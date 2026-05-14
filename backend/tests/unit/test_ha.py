from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.ha import get_ha_status
from api.health import get_health
from database import iceberg_detections, spoof_detections, trade_signals
from ha.journal import Journal
from ha.recovery import Recovery


@pytest.mark.asyncio
async def test_journal_write_creates_file(tmp_path, monkeypatch):
    journal_file = tmp_path / "ha" / "journal.log"
    monkeypatch.setattr("ha.journal.JOURNAL_PATH", journal_file)
    journal = Journal()
    await journal.write("iceberg", "RELIANCE", {"x": 1})
    assert journal_file.exists()


@pytest.mark.asyncio
async def test_journal_write_is_idempotent_append(tmp_path, monkeypatch):
    journal_file = tmp_path / "ha" / "journal.log"
    monkeypatch.setattr("ha.journal.JOURNAL_PATH", journal_file)
    journal = Journal()
    await journal.write("spoof", "RELIANCE", {"a": 1})
    await journal.write("spoof", "RELIANCE", {"a": 2})
    lines = journal_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


@pytest.mark.asyncio
async def test_journal_read_since_without_filter_returns_all(tmp_path, monkeypatch):
    journal_file = tmp_path / "ha" / "journal.log"
    monkeypatch.setattr("ha.journal.JOURNAL_PATH", journal_file)
    journal = Journal()
    await journal.write("signal", "TCS", {"score": 10})
    await journal.write("signal", "INFY", {"score": 12})
    assert len(journal.read_since()) == 2


@pytest.mark.asyncio
async def test_journal_read_since_filters_by_timestamp(tmp_path, monkeypatch):
    journal_file = tmp_path / "ha" / "journal.log"
    monkeypatch.setattr("ha.journal.JOURNAL_PATH", journal_file)
    journal = Journal()
    await journal.write("signal", "TCS", {"score": 10})
    mid = datetime.utcnow().isoformat()
    await journal.write("signal", "INFY", {"score": 12})
    filtered = journal.read_since(mid)
    assert len(filtered) == 1
    assert filtered[0]["symbol"] == "INFY"


@pytest.mark.asyncio
async def test_journal_last_checkpoint_returns_latest(tmp_path, monkeypatch):
    journal_file = tmp_path / "ha" / "journal.log"
    monkeypatch.setattr("ha.journal.JOURNAL_PATH", journal_file)
    journal = Journal()
    await journal.write("iceberg", "TCS", {"p": 1})
    await journal.write("spoof", "TCS", {"p": 2})
    assert journal.last_checkpoint() is not None


@pytest.mark.asyncio
async def test_recovery_replay_returns_correct_counts(tmp_path, monkeypatch):
    journal_file = tmp_path / "ha" / "journal.log"
    monkeypatch.setattr("ha.journal.JOURNAL_PATH", journal_file)
    journal = Journal()
    await journal.write("iceberg", "A", {})
    await journal.write("spoof", "A", {})
    await journal.write("signal", "A", {})
    await journal.write("circuit_break", "A", {})
    recovery = Recovery(journal)
    summary = await recovery.replay()
    assert summary["icebergs"] == 1
    assert summary["spoofs"] == 1
    assert summary["signals"] == 1
    assert summary["circuit_breaks"] == 1


@pytest.mark.asyncio
async def test_recovery_replay_handles_empty_journal(tmp_path, monkeypatch):
    journal_file = tmp_path / "ha" / "journal.log"
    monkeypatch.setattr("ha.journal.JOURNAL_PATH", journal_file)
    recovery = Recovery(Journal())
    summary = await recovery.replay()
    assert summary["total_events"] == 0
    assert summary["last_event_at"] is None


@pytest.mark.asyncio
async def test_recovery_summary_has_required_keys(tmp_path, monkeypatch):
    journal_file = tmp_path / "ha" / "journal.log"
    monkeypatch.setattr("ha.journal.JOURNAL_PATH", journal_file)
    recovery = Recovery(Journal())
    summary = await recovery.replay()
    required = {
        "total_events",
        "icebergs",
        "spoofs",
        "signals",
        "circuit_breaks",
        "last_event_at",
        "recovered",
    }
    assert required.issubset(summary.keys())


@pytest.mark.asyncio
async def test_health_endpoint_returns_required_fields(monkeypatch):
    monkeypatch.setattr("api.health.ping_database", AsyncMock(return_value=True))
    monkeypatch.setattr("api.health.journal.read_since", lambda *_args, **_kwargs: [{"ts": "2026-05-14T00:00:00"}])

    app = SimpleNamespace(
        state=SimpleNamespace(
            scheduler=SimpleNamespace(scheduler=SimpleNamespace(running=True)),
            started_at=datetime.now(timezone.utc) - timedelta(seconds=30),
        )
    )
    req = SimpleNamespace(app=app)
    result = await get_health(req)
    payload = result.model_dump()
    for key in [
        "status",
        "database",
        "scheduler",
        "kill_switch",
        "circuit_breakers_active",
        "journal_events",
        "last_journal_event",
        "uptime_seconds",
    ]:
        assert key in payload


def test_auto_restart_script_exists_and_executable():
    script = Path(__file__).resolve().parents[3] / "scripts" / "restart_backend.sh"
    assert script.exists()
    assert os.access(script, os.X_OK)


@pytest.mark.asyncio
async def test_ha_status_endpoint_returns_journal_events(monkeypatch):
    monkeypatch.setattr("api.ha.journal.read_since", lambda *_args, **_kwargs: [{"ts": "2026-05-14T01:00:00"}])

    class FakeDB:
        async def fetch_val(self, *_args, **_kwargs):
            return 7

    monkeypatch.setattr("api.ha.get_database", lambda: FakeDB())
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(recovery_summary={"total_events": 1})))
    payload = await get_ha_status(req)
    assert payload["journal_events"] == 1
    assert "sequence_numbers" in payload


def test_sequence_number_columns_exist_on_detection_tables():
    assert "seq_num" in iceberg_detections.c
    assert "seq_num" in spoof_detections.c
    assert "seq_num" in trade_signals.c
