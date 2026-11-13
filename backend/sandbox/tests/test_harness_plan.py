from __future__ import annotations

import glob
from datetime import date

import pandas as pd
import pytest
import requests

from harness import _place_leg, build_order_plan
from upstox_sandbox import RawApiLogger, UpstoxSandboxClient


def make_closes(start: date, days: int, curves: dict[str, list[float]]) -> pd.DataFrame:
    """Synthetic closes DataFrame indexed by business days (local helper — avoids
    cross-package import of the repo's own `tests` package)."""
    dates = pd.bdate_range(start=start, periods=days)
    return pd.DataFrame({sym: pd.Series(vals, index=dates) for sym, vals in curves.items()})


def test_build_order_plan_selects_top1_buy_leg():
    days = 40
    closes = make_closes(date(2026, 1, 1), days, {
        "A": [100.0] * 19 + [112.0] * 21,
        "B": [100.0] * 19 + [105.0] * 21,
        "C": [100.0] * 40,
    })
    adv = {"A": 1e9, "B": 1e9, "C": 1e9}
    plan = build_order_plan(closes, adv, rebalance=date(2026, 2, 25), budget=1_000_000.0)
    # 3 symbols -> top-quartile = max(1, 3//4) = 1, so the basket is still "A".
    assert [l["symbol"] for l in plan["legs"]] == ["A"]
    leg = plan["legs"][0]
    assert leg["side"] == "BUY"
    assert leg["qty"] == 8928  # floor(1_000_000 / 112.0)
    assert leg["ref_price"] == pytest.approx(112.0)
    assert leg["rank"] == 1
    assert leg["assumed_cost_inr"] > 0.0


def test_build_order_plan_selects_quartile_basket_and_splits_budget():
    # 8 symbols -> top-quartile = 8 // 4 = 2 names, budget split across both.
    days = 40
    curves = {
        "A": [100.0] * 19 + [112.0] * 21,   # +12%
        "B": [100.0] * 19 + [110.0] * 21,   # +10%
        "C": [100.0] * 19 + [108.0] * 21,   # +8%
        "D": [100.0] * 19 + [106.0] * 21,   # +6%
        "E": [100.0] * 19 + [104.0] * 21,   # +4%
        "F": [100.0] * 19 + [102.0] * 21,   # +2%
        "G": [100.0] * 40,
        "H": [100.0] * 40,
    }
    closes = make_closes(date(2026, 1, 1), days, curves)
    adv = {s: 1e9 for s in curves}
    plan = build_order_plan(closes, adv, rebalance=date(2026, 2, 25), budget=1_000_000.0)
    assert plan["k"] == 2
    assert [l["symbol"] for l in plan["legs"]] == ["A", "B"]
    assert all(l["side"] == "BUY" for l in plan["legs"])
    # Budget split across the 2-name basket: floor(500_000 / ref_price).
    by_sym = {l["symbol"]: l for l in plan["legs"]}
    assert by_sym["A"]["qty"] == 4464  # floor(500_000 / 112.0)
    assert by_sym["B"]["qty"] == 4545  # floor(500_000 / 110.0)
    assert by_sym["A"]["rank"] == 1
    assert by_sym["B"]["rank"] == 2
    assert all(l["assumed_cost_inr"] > 0.0 for l in plan["legs"])


def test_build_order_plan_records_previous_basket():
    days = 60
    # B was the top name at the previous month's rebalance (Feb 27 = row 41); A
    # becomes the top name at the current rebalance (Mar 25 = row 59, the last
    # trading day of March in the synthetic business-day calendar).
    #   A: 100 for rows 0-38, then 112 -> +12% at Feb 27 AND at Mar 25.
    #   B: 100 for rows 0-20, 115 for rows 21-41, 103 for rows 42-59
    #      -> +15% at Feb 27 (beats A), -10.4% at Mar 25 (loses to A).
    closes = make_closes(date(2026, 1, 1), days, {
        "A": [100.0] * 39 + [112.0] * 21,
        "B": [100.0] * 21 + [115.0] * 21 + [103.0] * 18,
        "C": [100.0] * 60,
    })
    adv = {"A": 1e9, "B": 1e9, "C": 1e9}
    # 2026-03-25 is the last trading day of March in the synthetic calendar.
    plan = build_order_plan(closes, adv, rebalance=date(2026, 3, 25), budget=500_000.0)
    assert plan["legs"][0]["symbol"] == "A"
    assert plan["previous_basket"] == ["B"]  # 3-symbol universe -> quartile of 1
    assert plan["previous_rebalance_date"] == date(2026, 2, 27).isoformat()


def test_build_order_plan_resolves_previous_basket_price():
    days = 60
    closes = make_closes(date(2026, 1, 1), days, {
        "A": [100.0] * 39 + [112.0] * 21,
        "B": [100.0] * 21 + [115.0] * 21 + [103.0] * 18,
        "C": [100.0] * 60,
    })
    plan = build_order_plan(closes, {"A": 1e9, "B": 1e9, "C": 1e9},
                            rebalance=date(2026, 3, 25), budget=1e6)
    # B was in the previous basket (top-1 of 3) on Feb 27 at 115.0.
    assert plan["previous_basket"] == ["B"]
    assert plan["previous_basket_prices"]["B"] == pytest.approx(115.0)


def test_build_order_plan_no_previous_rebalance_price_is_none():
    days = 15
    # Calendar starts 2026-01-01; no month-end (Jan 30) has occurred before
    # 2026-01-20, so there is no rotation context.
    closes = make_closes(date(2026, 1, 1), days, {"A": [100.0] * 15})
    plan = build_order_plan(closes, {"A": 1e9}, rebalance=date(2026, 1, 20), budget=1e6)
    assert plan["previous_basket"] == []
    assert plan["previous_basket_prices"] == {}


def test_plan_ranking_table_has_all_symbols():
    days = 40
    closes = make_closes(date(2026, 1, 1), days, {"A": [100.0] * 40, "B": [100.0] * 40})
    plan = build_order_plan(closes, {"A": 1e9, "B": 1e9}, rebalance=date(2026, 2, 25), budget=1e6)
    assert len(plan["ranking"]) == 2


class _FakeTransport:
    """Fake requests.request that returns a canned response and records calls."""

    def __init__(self, monkeypatch, status=200, payload=None):
        self.calls: list[tuple] = []
        self.status = status
        self.payload = payload if payload is not None else {"status": "success", "data": {"order_id": "SANDBOX-42"}}

        class _Resp:
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self._payload = payload
                self.headers = {"Content-Type": "application/json"}

            def json(self):
                return self._payload

            @property
            def text(self):
                return str(self._payload)

        def _fake_request(method, url, json=None, params=None, headers=None, timeout=None):
            self.calls.append((method, url, json, params, headers))
            return _Resp(self.status, self.payload)

        monkeypatch.setattr("upstox_sandbox.requests.request", _fake_request)


def test_client_place_order_sends_v2_payload_and_extracts_order_id(tmp_path, monkeypatch):
    transport = _FakeTransport(monkeypatch)
    raw = RawApiLogger(str(tmp_path))
    client = UpstoxSandboxClient("fake-sandbox-token", raw_logger=raw)
    result = client.place_order(
        quantity=42, instrument_token="NSE_EQ|3045", transaction_type="BUY",
        order_type="MARKET", tag="alphacore-k1-test",
    )
    assert result["order_id"] == "SANDBOX-42"
    method, url, body, params, headers = transport.calls[0]
    assert method == "POST"
    assert url == "https://api-sandbox.upstox.com/v2/order/place"
    assert body["quantity"] == 42
    assert body["instrument_token"] == "NSE_EQ|3045"
    assert body["transaction_type"] == "BUY"
    assert body["order_type"] == "MARKET"
    assert body["product"] == "D"
    assert body["validity"] == "DAY"
    assert headers["Authorization"] == "Bearer fake-sandbox-token"

    # Raw log must contain the request/response verbatim.
    raw.close()
    log_text = (tmp_path / raw.path.split("/")[-1]).read_text() if raw.path.startswith(str(tmp_path)) else ""
    if not log_text:
        log_text = open(glob.glob(str(tmp_path) + "/*.txt")[0]).read()
    assert "POST https://api-sandbox.upstox.com/v2/order/place" in log_text
    assert '"order_id": "SANDBOX-42"' in log_text


def test_client_rejects_empty_token():
    with pytest.raises(ValueError, match="UPSTOX_SANDBOX_TOKEN"):
        UpstoxSandboxClient("   ")


def test_client_logs_raw_rejection(tmp_path, monkeypatch):
    payload = {"status": "error", "errors": [{"code": "UDAPI1052", "message": "quantity cannot be zero"}]}
    _FakeTransport(monkeypatch, status=400, payload=payload)
    raw = RawApiLogger(str(tmp_path))
    client = UpstoxSandboxClient("tok", raw_logger=raw)
    result = client.place_order(quantity=0, instrument_token="NSE_EQ|3045", transaction_type="BUY")
    assert result["status_code"] == 400
    assert result["response"]["errors"][0]["code"] == "UDAPI1052"


def test_place_leg_records_transport_error_not_crash(tmp_path, monkeypatch):
    """A network failure must be recorded as a leg, never crash the run."""

    def _raise(method, url, json=None, params=None, headers=None, timeout=None):
        raise requests.ConnectionError("sandbox unreachable")

    monkeypatch.setattr("upstox_sandbox.requests.request", _raise)
    raw = RawApiLogger(str(tmp_path))
    client = UpstoxSandboxClient("tok", raw_logger=raw)
    plan = {"rebalance_date": "2026-06-30", "legs": []}
    leg = {"symbol": "TCS", "side": "BUY", "qty": 10, "ref_price": 4000.0,
           "adv_inr": 1e9, "assumed_cost_inr": 120.0}
    # instrument_keys must contain a real master key for TCS: there is no
    # numeric-token fallback anymore, so an empty lookup would raise BEFORE
    # the transport layer is ever reached.
    record = _place_leg(client, raw, plan, leg,
                        instrument_keys={"TCS": "NSE_EQ|INE467B01029"},
                        order_type="MARKET", limit_price=None, is_amo=False)
    assert record["fill_status"] == "TRANSPORT_ERROR"
    assert "sandbox unreachable" in record["fill_reason"]
    assert record["order_id"] is None
    assert record["place_status_code"] is None
    raw.close()
    log_text = open(glob.glob(str(tmp_path) + "/*.txt")[0]).read()
    assert "TRANSPORT ERROR: sandbox unreachable" in log_text
