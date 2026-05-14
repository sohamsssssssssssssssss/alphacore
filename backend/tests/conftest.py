import pytest
from datetime import datetime, timezone
from models.schemas import OrderBookSnapshot, OrderLevel
from unittest.mock import AsyncMock

MOCK_ORDER_BOOK = {
    "symbol": "RELIANCE",
    "bids": [
        {"price": 2890.0, "volume": 1000},
        {"price": 2889.0, "volume": 1500},
        {"price": 2888.0, "volume": 2000},
        {"price": 2887.0, "volume": 1200},
        {"price": 2886.0, "volume": 800},
    ],
    "asks": [
        {"price": 2891.0, "volume": 900},
        {"price": 2892.0, "volume": 1100},
        {"price": 2893.0, "volume": 1300},
        {"price": 2894.0, "volume": 700},
        {"price": 2895.0, "volume": 600},
    ],
    "spread": 1.0,
    "bid_ask_imbalance": 0.35,
    "total_bid_volume": 6500,
    "total_ask_volume": 4600,
}

MOCK_SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]


@pytest.fixture
def mock_order_book():
    return MOCK_ORDER_BOOK.copy()


@pytest.fixture
def mock_symbols():
    return MOCK_SYMBOLS.copy()


@pytest.fixture
def bullish_order_book():
    book = MOCK_ORDER_BOOK.copy()
    book["bid_ask_imbalance"] = 0.6
    book["total_bid_volume"] = 10000
    book["total_ask_volume"] = 3000
    return book


@pytest.fixture
def bearish_order_book():
    book = MOCK_ORDER_BOOK.copy()
    book["bid_ask_imbalance"] = -0.6
    book["total_bid_volume"] = 2000
    book["total_ask_volume"] = 9000
    return book


@pytest.fixture
def sample_snapshot():
    return OrderBookSnapshot(
        symbol="RELIANCE",
        timestamp=datetime.now(timezone.utc),
        bids=[OrderLevel(price=2890.0 - i, volume=1000 + i * 10) for i in range(5)],
        asks=[OrderLevel(price=2891.0 + i, volume=900 + i * 10) for i in range(5)],
        spread=1.0,
        bid_ask_imbalance=0.25,
        total_bid_volume=5100,
        total_ask_volume=4600,
    )


@pytest.fixture(autouse=True)
def mock_db(monkeypatch):
    # Mock database calls for API tests that don't need real DB
    class _FakeDB:
        fetch_all = AsyncMock(return_value=[])
        fetch_one = AsyncMock(return_value=None)
        fetch_val = AsyncMock(return_value=0)
        execute = AsyncMock(return_value=1)

    monkeypatch.setattr("database.get_database", lambda: _FakeDB(), raising=False)
