from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from data.yfinance_feed import IST, MarketHoursChecker, YFinanceFeed


def _fake_df(ts, close=123.45):
    idx = pd.DatetimeIndex([ts])
    return pd.DataFrame(
        {
            "Open": [120.0],
            "High": [125.0],
            "Low": [119.0],
            "Close": [close],
            "Volume": [1000.0],
        },
        index=idx,
    )


def test_is_alive_after_start(monkeypatch):
    monkeypatch.setattr("data.yfinance_feed.MarketHoursChecker.is_market_open", lambda: False)
    feed = YFinanceFeed(symbols=["RELIANCE"], poll_interval_seconds=0.05)
    feed.start()
    assert feed.is_alive() is True
    feed.stop()
    assert feed.is_alive() is False


def test_get_latest_returns_none_before_data():
    feed = YFinanceFeed(symbols=["RELIANCE"])
    assert feed.get_latest("RELIANCE") is None


def test_on_tick_callback_fires(monkeypatch):
    feed = YFinanceFeed(symbols=["RELIANCE"])
    seen = []
    feed.on_tick(lambda tick: seen.append(tick))

    ts = datetime.now(IST)
    monkeypatch.setattr("data.yfinance_feed.yf.download", lambda *a, **k: _fake_df(ts, close=2400.0))
    feed._poll_once()

    assert len(seen) == 1
    assert seen[0]["symbol"] == "RELIANCE"
    assert seen[0]["close"] == 2400.0


def test_market_hours_checker_weekday(monkeypatch):
    dt = datetime(2026, 5, 18, 10, 0, tzinfo=IST)  # Monday
    monkeypatch.setattr("data.yfinance_feed.MarketHoursChecker.now_ist", lambda: dt)
    assert MarketHoursChecker.is_market_open() is True


def test_market_hours_checker_closed(monkeypatch):
    dt = datetime(2026, 5, 18, 20, 0, tzinfo=IST)  # Monday
    monkeypatch.setattr("data.yfinance_feed.MarketHoursChecker.now_ist", lambda: dt)
    assert MarketHoursChecker.is_market_open() is False


def test_market_hours_checker_weekend(monkeypatch):
    dt = datetime(2026, 5, 16, 10, 0, tzinfo=IST)  # Saturday
    monkeypatch.setattr("data.yfinance_feed.MarketHoursChecker.now_ist", lambda: dt)
    assert MarketHoursChecker.is_market_open() is False


def test_duplicate_bar_not_refired(monkeypatch):
    feed = YFinanceFeed(symbols=["RELIANCE"])
    seen = []
    feed.on_tick(lambda tick: seen.append(tick))

    ts = datetime.now(timezone.utc)
    monkeypatch.setattr("data.yfinance_feed.yf.download", lambda *a, **k: _fake_df(ts, close=2000.0))
    feed._poll_once()
    feed._poll_once()

    assert len(seen) == 1
