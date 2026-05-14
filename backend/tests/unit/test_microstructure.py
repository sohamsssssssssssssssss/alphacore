from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engines.liquidity_score import LiquidityScorer
from engines.market_impact import MarketImpactModel
from engines.spread_tracker import SpreadTracker
from engines.vwap import VWAPEngine


@pytest.mark.asyncio
async def test_vwap_single_update():
    engine = VWAPEngine()
    await engine.update("RELIANCE", 100.0, 10.0, datetime.now(timezone.utc))
    assert engine.get_vwap("RELIANCE", "5min") == 100.0


@pytest.mark.asyncio
async def test_vwap_multiple_updates_weighted():
    engine = VWAPEngine()
    now = datetime.now(timezone.utc)
    await engine.update("RELIANCE", 100.0, 10.0, now)
    await engine.update("RELIANCE", 200.0, 30.0, now)
    assert engine.get_vwap("RELIANCE", "5min") == pytest.approx(175.0)


@pytest.mark.asyncio
async def test_vwap_window_expiry():
    engine = VWAPEngine()
    now = datetime.now(timezone.utc)
    old = now - timedelta(minutes=10)
    await engine.update("RELIANCE", 100.0, 10.0, old)
    await engine.update("RELIANCE", 200.0, 10.0, now)
    assert engine.get_vwap("RELIANCE", "1min") == 200.0


@pytest.mark.asyncio
async def test_vwap_deviation_bps():
    engine = VWAPEngine()
    now = datetime.now(timezone.utc)
    await engine.update("RELIANCE", 100.0, 1.0, now)
    dev = engine.get_vwap_deviation("RELIANCE", 101.0)
    assert dev == pytest.approx(100.0)


def test_spread_tracker_absolute():
    tracker = SpreadTracker()
    tracker.update("RELIANCE", 100.0, 101.0)
    assert tracker.get_spread("RELIANCE")["absolute"] == 1.0


def test_spread_tracker_relative_bps():
    tracker = SpreadTracker()
    tracker.update("RELIANCE", 100.0, 101.0)
    assert tracker.get_spread("RELIANCE")["relative"] == pytest.approx((1.0 / 100.5) * 10000)


def test_spread_tracker_history():
    tracker = SpreadTracker()
    for i in range(3):
      tracker.update("RELIANCE", 100.0 + i, 101.0 + i)
    assert len(tracker.get_spread_history("RELIANCE", n=10)) == 3


def test_liquidity_score_perfect():
    scorer = LiquidityScorer()
    scorer.update("RELIANCE", spread_bps=0.0, depth=10_000_000, otr=0.0, price_history=[100.0] * 10)
    score = scorer.get_score("RELIANCE")
    assert score["total"] > 90


def test_liquidity_score_grade_A():
    scorer = LiquidityScorer()
    scorer.update("RELIANCE", spread_bps=2.0, depth=1_000_000, otr=1.0, price_history=[100.0, 100.1, 99.9])
    assert scorer.get_score("RELIANCE")["grade"] == "A"


def test_liquidity_score_grade_F():
    scorer = LiquidityScorer()
    scorer.update("RELIANCE", spread_bps=1000.0, depth=1.0, otr=100.0, price_history=[100.0, 120.0, 80.0])
    assert scorer.get_score("RELIANCE")["grade"] == "F"


def test_liquidity_all_components():
    scorer = LiquidityScorer()
    scorer.update("TCS", spread_bps=10.0, depth=1000.0, otr=2.0, price_history=[100.0, 101.0])
    components = scorer.get_score("TCS")["components"]
    assert set(components.keys()) == {"spread", "depth", "otr", "volatility"}


def test_market_impact_temporary():
    model = MarketImpactModel()
    tmp = model.temporary_impact(1000, 1_000_000, 10)
    assert tmp > 5


def test_market_impact_permanent():
    model = MarketImpactModel()
    perm = model.permanent_impact(1000, 1_000_000)
    assert perm > 0


def test_market_impact_total():
    model = MarketImpactModel()
    total = model.total_impact(1000, 1_000_000, 10)
    assert total["total_bps"] == pytest.approx(total["temporary_bps"] + total["permanent_bps"])


def test_market_impact_curve_20_points():
    model = MarketImpactModel()
    curve = model.price_impact_curve(1_000_000, 10)
    assert len(curve) == 20


def test_vwap_get_all_has_all_windows():
    engine = VWAPEngine()
    all_ = engine.get_all("RELIANCE")
    assert set(all_.keys()) == {"1min", "5min", "15min", "session"}
