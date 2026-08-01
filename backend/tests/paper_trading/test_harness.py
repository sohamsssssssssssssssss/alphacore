"""Tests for the paper-trading harness (sandbox scheduler core logic).

Uses a fake order client / fake quote data — no network, no orders.
Run: python3.11 -m pytest backend/tests/paper_trading/test_harness.py -q
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test_paper_harness.db")

import pytest

BACKEND = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND))

from paper_trading import config  # noqa: E402
from paper_trading.costs import (  # noqa: E402
    modeled_cost_rs, realized_slippage_bps, spread_bps)
from paper_trading.events import EventLog  # noqa: E402
from paper_trading.market_data import CloseHistory, parse_quote  # noqa: E402
from paper_trading.strategy import Strategy, verify_port  # noqa: E402


@pytest.fixture()
def tmp_state(tmp_path):
    config.STATE_DIR = tmp_path
    config.LOG_FILE = tmp_path / "logs" / "events.jsonl"
    config.CLOSE_HISTORY_FILE = tmp_path / "close_history.json"
    config.KILL_FILE = tmp_path / "KILL"
    config.STATE_FILE = tmp_path / "state.json"
    return tmp_path


@pytest.fixture()
def symbols():
    return sorted(p.stem for p in config.DATA_DIR_50.glob("*.csv"))


@pytest.fixture()
def history(symbols):
    h = CloseHistory()
    n = h.seed_from_csv(symbols)
    assert n == 49
    return h


class TestQuoteParsing:
    def test_depth_parse(self):
        q = parse_quote({"last_price": 100.0,
                         "depth": {"market_orders": [
                             {"price": 99.9, "quantity": 100, "order_side": "buy"},
                             {"price": 100.1, "quantity": 100, "order_side": "sell"}]}})
        assert q["bid"] == 99.9
        assert q["ask"] == 100.1
        assert q["depth_ok"]

    def test_no_depth_uses_last(self):
        q = parse_quote({"last_price": 123.4})
        assert q["last"] == 123.4
        assert not q["depth_ok"]


class TestStrategy:
    def test_picks_are_extremes(self, history):
        strat = Strategy(history.series.keys())
        top, bottom = strat.pick_positions(history)
        ranks = strat.signal_ranks(history)
        assert ranks[top] == max(ranks.values())
        assert ranks[bottom] == min(ranks.values())
        assert top != bottom

    def test_rebalance_day_counting(self, history):
        strat = Strategy(history.series.keys())
        last = "2026-07-29"  # seed end; no days since
        assert not strat.is_rebalance_day(history, last)
        # simulate 21 captured trading days after seed end (all symbols capture)
        for i in range(1, 23):
            date = f"2026-08-{i:02d}"
            history.append_day(date, {s: 1000.0 + i for s in strat.symbols})
        assert strat.is_rebalance_day(history, last)
        assert strat.is_rebalance_day(history, "2026-08-01")  # 21 days by 08-22
        assert not strat.is_rebalance_day(history, "2026-08-22")

    def test_plan_rebalance_builds_closes_and_opens(self, history):
        strat = Strategy(history.series.keys())
        for i in range(1, 22):
            history.append_day(f"2026-08-{i:02d}", {"RELIANCE": 1000.0 + i})
        quotes = {"HCLTECH": {"last": 2000.0, "bid": 1999.5, "ask": 2000.5,
                              "depth_ok": True},
                  "DRREDDY": {"last": 3000.0, "bid": 2999.5, "ask": 3000.5,
                              "depth_ok": True}}
        plan = strat.plan_rebalance(history, 100000.0, {}, quotes)
        assert plan["long"]["symbol"] == "HCLTECH"
        assert plan["short"]["symbol"] == "DRREDDY"
        assert len(plan["opens"]) == 2
        assert plan["opens"][0]["side"] == "BUY"
        assert plan["opens"][1]["side"] == "SELL"
        assert all(o["qty"] > 0 for o in plan["opens"])
        assert plan["closes"] == []

    def test_quantity_floor(self):
        strat = Strategy(["A"])
        assert strat.quantity(100000.0, 2000.0) == 5   # 0.10*100000/2000
        assert strat.quantity(100000.0, 3001.0) == 3   # floored


class TestCosts:
    def test_slippage_buy_adverse(self):
        assert realized_slippage_bps(100.1, 100.0, "BUY") == pytest.approx(10.0)
        assert realized_slippage_bps(100.0, 100.0, "BUY") == 0.0

    def test_slippage_sell_adverse(self):
        assert realized_slippage_bps(99.9, 100.0, "SELL") == pytest.approx(10.0)
        assert realized_slippage_bps(100.0, 100.0, "SELL") == 0.0

    def test_spread_bps_clamped(self):
        assert spread_bps(99.0, 101.0, 100.0) == 50.0          # clamped upper
        assert spread_bps(99.9995, 100.0005, 100.0) == 0.5     # clamped lower
        assert spread_bps(99.9, 100.1, 100.0) == pytest.approx(20.0)
        assert spread_bps(None, 100.1, 100.0) is None

    def test_modeled_cost_nonzero(self):
        c = modeled_cost_rs(1000.0, 10, 20.0, "BUY")
        assert c > 0  # impact + half-spread + brokerage
        # sells add STT
        c_sell = modeled_cost_rs(1000.0, 10, 20.0, "SELL")
        assert c_sell > c


class TestVerifyPort:
    def test_matches_backtest_math(self, history, symbols):
        result = verify_port(history, symbols)
        assert result["ok"]
