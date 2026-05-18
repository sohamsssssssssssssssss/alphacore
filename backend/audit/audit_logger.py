from __future__ import annotations

import csv
import json
import os
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

VALID_EVENT_TYPES = {
    "ORDER_SUBMIT",
    "ORDER_ACK",
    "ORDER_REJECT",
    "ORDER_CANCEL",
    "PARTIAL_FILL",
    "FULL_FILL",
    "RISK_VIOLATION",
    "STRATEGY_SIGNAL",
    "REGIME_CHANGE",
    "EOD_FLATTEN",
    "PAPER_TRADE",
    "SESSION_START",
    "SESSION_END",
}

IST = timezone(timedelta(hours=5, minutes=30), name="IST")


class AuditLogger:
    def __init__(self, db_url: str | None = None):
        resolved_db_url = db_url or os.getenv("ALPHACORE_AUDIT_DB") or "postgresql://localhost/alphacore"
        self.db_url = resolved_db_url
        self.engine: Engine = sa.create_engine(self.db_url, future=True)
        self._is_sqlite = self.engine.dialect.name == "sqlite"
        self._init_schema()

    def _init_schema(self) -> None:
        if self._is_sqlite:
            with self.engine.begin() as conn:
                conn.execute(
                    sa.text(
                        """
                        CREATE TABLE IF NOT EXISTS audit_log (
                            seq INTEGER PRIMARY KEY AUTOINCREMENT,
                            logged_at TEXT NOT NULL,
                            event_type TEXT NOT NULL,
                            symbol TEXT NOT NULL,
                            side TEXT,
                            qty NUMERIC,
                            price NUMERIC,
                            strategy_id TEXT,
                            order_id TEXT,
                            extra TEXT
                        )
                        """
                    )
                )
            return

        with self.engine.begin() as conn:
            conn.execute(
                sa.text(
                    """
                    CREATE TABLE IF NOT EXISTS audit_log (
                        seq BIGSERIAL PRIMARY KEY,
                        logged_at TIMESTAMPTZ NOT NULL,
                        event_type TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        side TEXT,
                        qty NUMERIC,
                        price NUMERIC,
                        strategy_id TEXT,
                        order_id TEXT,
                        extra JSONB
                    ) PARTITION BY RANGE (logged_at)
                    """
                )
            )
            self._ensure_partition(conn, datetime.now(UTC))
            conn.execute(
                sa.text(
                    """
                    CREATE OR REPLACE FUNCTION audit_log_block_mutations()
                    RETURNS trigger AS $$
                    BEGIN
                        RAISE EXCEPTION 'audit_log is append-only';
                    END;
                    $$ LANGUAGE plpgsql;
                    """
                )
            )
            conn.execute(
                sa.text(
                    """
                    DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log;
                    CREATE TRIGGER audit_log_no_update
                    BEFORE UPDATE ON audit_log
                    FOR EACH ROW EXECUTE FUNCTION audit_log_block_mutations();
                    """
                )
            )
            conn.execute(
                sa.text(
                    """
                    DROP TRIGGER IF EXISTS audit_log_no_delete ON audit_log;
                    CREATE TRIGGER audit_log_no_delete
                    BEFORE DELETE ON audit_log
                    FOR EACH ROW EXECUTE FUNCTION audit_log_block_mutations();
                    """
                )
            )

    def _ensure_partition(self, conn: sa.Connection, ts_utc: datetime) -> None:
        month_start = ts_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if month_start.month == 12:
            next_month = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month = month_start.replace(month=month_start.month + 1)

        part_name = f"audit_log_{month_start.year}{month_start.month:02d}"
        conn.execute(
            sa.text(
                f"""
                CREATE TABLE IF NOT EXISTS {part_name}
                PARTITION OF audit_log
                FOR VALUES FROM (:start_ts) TO (:end_ts)
                """
            ),
            {"start_ts": month_start, "end_ts": next_month},
        )

    @staticmethod
    def _parse_yyyy_mm_dd(s: str) -> datetime:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=IST)

    @staticmethod
    def _to_ist_str(ts: datetime) -> str:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        ts_ist = ts.astimezone(IST)
        return ts_ist.strftime("%Y-%m-%d %H:%M:%S.%f IST")

    def append(self, event: dict) -> int:
        if "event_type" not in event:
            raise ValueError("event_type is required")
        if "symbol" not in event or not str(event.get("symbol", "")).strip():
            raise ValueError("symbol is required")

        event_type = str(event["event_type"]).upper()
        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(f"invalid event_type: {event_type}")

        known = {"event_type", "symbol", "side", "qty", "price", "strategy_id", "order_id"}
        extra = {k: v for k, v in event.items() if k not in known}

        side_in = event.get("side")
        if side_in is None:
            side = "N/A"
        else:
            side_norm = str(side_in).upper()
            side = side_norm if side_norm in {"BUY", "SELL"} else "N/A"

        logged_at = datetime.now(UTC)
        row = {
            "logged_at": logged_at,
            "event_type": event_type,
            "symbol": str(event["symbol"]).upper(),
            "side": side,
            "qty": event.get("qty"),
            "price": event.get("price"),
            "strategy_id": event.get("strategy_id"),
            "order_id": event.get("order_id"),
            "extra": extra,
        }

        with self.engine.begin() as conn:
            if not self._is_sqlite:
                self._ensure_partition(conn, logged_at)
                seq = conn.execute(
                    sa.text(
                        """
                        INSERT INTO audit_log
                        (logged_at, event_type, symbol, side, qty, price, strategy_id, order_id, extra)
                        VALUES (:logged_at, :event_type, :symbol, :side, :qty, :price, :strategy_id, :order_id, CAST(:extra AS JSONB))
                        RETURNING seq
                        """
                    ),
                    {**row, "extra": json.dumps(row["extra"])},
                ).scalar_one()
            else:
                seq = conn.execute(
                    sa.text(
                        """
                        INSERT INTO audit_log
                        (logged_at, event_type, symbol, side, qty, price, strategy_id, order_id, extra)
                        VALUES (:logged_at, :event_type, :symbol, :side, :qty, :price, :strategy_id, :order_id, :extra)
                        """
                    ),
                    {**row, "logged_at": logged_at.isoformat(), "extra": json.dumps(row["extra"])},
                ).lastrowid
        return int(seq)

    def _fetch_range_rows(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        start_ist = self._parse_yyyy_mm_dd(start_date)
        end_ist = self._parse_yyyy_mm_dd(end_date)
        start_utc = start_ist.astimezone(UTC)
        end_utc = (end_ist + timedelta(days=1)).astimezone(UTC)

        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    """
                    SELECT seq, logged_at, event_type, symbol, side, qty, price, strategy_id, order_id, extra
                    FROM audit_log
                    WHERE logged_at >= :start_utc AND logged_at < :end_utc
                    ORDER BY seq ASC
                    """
                ),
                {
                    "start_utc": start_utc.isoformat() if self._is_sqlite else start_utc,
                    "end_utc": end_utc.isoformat() if self._is_sqlite else end_utc,
                },
            ).mappings().all()

        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            if self._is_sqlite:
                ts = datetime.fromisoformat(str(item["logged_at"]))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                item["logged_at"] = ts
            extra_raw = item.get("extra")
            if isinstance(extra_raw, str):
                try:
                    item["extra"] = json.loads(extra_raw)
                except json.JSONDecodeError:
                    item["extra"] = {"raw": extra_raw}
            elif extra_raw is None:
                item["extra"] = {}
            out.append(item)
        return out

    def export_csv(self, start_date: str, end_date: str, path: str) -> int:
        rows = self._fetch_range_rows(start_date, end_date)
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cols = ["seq", "logged_at", "event_type", "symbol", "side", "qty", "price", "strategy_id", "order_id", "extra"]

        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "seq": row.get("seq"),
                        "logged_at": self._to_ist_str(row["logged_at"]),
                        "event_type": row.get("event_type"),
                        "symbol": row.get("symbol"),
                        "side": row.get("side"),
                        "qty": row.get("qty"),
                        "price": row.get("price"),
                        "strategy_id": row.get("strategy_id"),
                        "order_id": row.get("order_id"),
                        "extra": json.dumps(row.get("extra", {}), sort_keys=True),
                    }
                )
        return int(len(rows))

    def replay_session(self, session_date: str) -> list[dict]:
        return self._fetch_range_rows(session_date, session_date)

    def count(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(sa.text("SELECT COUNT(*) FROM audit_log")).scalar_one())
