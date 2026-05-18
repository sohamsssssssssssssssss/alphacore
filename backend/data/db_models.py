from __future__ import annotations

from sqlalchemy import Column, DateTime, String, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.types import JSON

Base = declarative_base()


class OrderBookSnapshot(Base):
    __tablename__ = "order_book_snapshots"

    timestamp = Column(DateTime, primary_key=True)
    symbol = Column(String(20), primary_key=True)
    bids = Column(JSONB().with_variant(JSON, "sqlite"), nullable=False)
    asks = Column(JSONB().with_variant(JSON, "sqlite"), nullable=False)
    features = Column(JSONB().with_variant(JSON, "sqlite"), nullable=False)


def get_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True)


def create_tables(engine: Engine) -> None:
    Base.metadata.create_all(engine)
