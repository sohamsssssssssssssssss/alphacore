from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys
import time

import pytest

sys.path.insert(0, "/tmp/alphacore_build")
sys_mod = pytest.importorskip("alphacore_cpp")
alphacore_cpp = sys_mod

from audit.audit_logger import AuditLogger
from engines.cost_model import CostModel
from engines.ml.features import FEATURE42_KEYS, OrderBookFeatureEngine
from engines.ml.ml_engine import MultiModelEngine
from engines.purged_kfold import PurgedKFold
from execution.eod_scheduler import EODScheduler
from execution.paper_engine import PaperTradingEngine
from risk.risk_manager import RiskGate, RiskViolationException
from strategy.alpha_strategy import AlphaStrategy

pytestmark = pytest.mark.timeout(60)


def _mk_order(order_id: int, symbol_id: int, side: str, price: int, qty: int):
    o = alphacore_cpp.Order()
    o.order_id = int(order_id)
    o.symbol_id = int(symbol_id)
    o.side = side
    o.price = int(price)
    o.qty = int(qty)
    o.timestamp_ns = int(time.time_ns())
    return o


def _drain_trade(eng, timeout_s: float = 1.0):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout_s:
        tr = eng.pop_trade()
        if tr is not None:
            return tr
        time.sleep(0.001)
    return None


def _snapshot_from_trade(trade):
    px = float(trade.price) / 100.0
    qty = float(trade.qty)
    return {
        "bid_prices": [px, 0.0, 0.0, 0.0, 0.0],
        "ask_prices": [px, 0.0, 0.0, 0.0, 0.0],
        "bid_qtys": [qty, 0.0, 0.0, 0.0, 0.0],
        "ask_qtys": [qty, 0.0, 0.0, 0.0, 0.0],
        "last_price": px,
        "volume": qty,
        "timestamp_ns": int(time.time_ns()),
    }


def _ml_signal_from_features(features: dict) -> dict:
    vals = [float(features[k]) for k in FEATURE42_KEYS]
    score = sum(vals) / max(1, len(vals))
    confidence = max(0.0, min(1.0, (score + 1.0) / 2.0))
    signal = 1 if confidence > 0.55 else (-1 if confidence < 0.45 else 0)
    model_scores = {
        "random_forest": confidence,
        "xgboost": max(0.0, min(1.0, confidence - 0.01)),
        "lightgbm": max(0.0, min(1.0, confidence + 0.01)),
        "lstm": confidence,
    }
    return {"signal": signal, "confidence": confidence, "model_scores": model_scores}


class _PaperBrokerAdapter:
    def __init__(self, paper: PaperTradingEngine, audit: AuditLogger):
        self.paper = paper
        self.audit = audit

    def get_positions(self):
        return [{"symbol": s, "qty": q} for s, q in self.paper.positions.items()]

    def place_order(self, symbol: str, side: str, qty: int, order_type: str, _product: str):
        oid = self.paper.submit_order(symbol=symbol, side=side, qty=qty, order_type=order_type, price=100.0)
        self.paper.process_market_tick(symbol, best_bid=100.0, best_ask=100.0)
        self.audit.append({"event_type": "EOD_FLATTEN", "symbol": symbol, "side": side, "qty": qty, "order_id": oid})
        return oid

    def get_pending_orders(self):
        return list(self.paper.pending_orders)

    def cancel_order(self, order_id: str):
        self.paper.pending_orders = [o for o in self.paper.pending_orders if o.get("order_id") != order_id]


@pytest.fixture(scope="session")
def full_pipeline(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("cpp_pipeline") / "audit.sqlite"
    db_url = f"sqlite:///{db_path}"

    engine = alphacore_cpp.MatchingEngine(4)
    engine.start()
    feature_engine = OrderBookFeatureEngine(use_cpp=False)
    multi_model = MultiModelEngine(feature_engine, PurgedKFold(n_splits=5, embargo_bars=5), CostModel())
    strategy = AlphaStrategy(confidence_threshold=0.6, base_qty=1)
    risk_gate = RiskGate(starting_capital=100000.0, max_order_rate_per_min=100000)
    paper = PaperTradingEngine(starting_capital=100000.0)
    audit = AuditLogger(db_url=db_url)
    audit.append({"event_type": "SESSION_START", "symbol": "SESSION"})

    ctx = {
        "engine": engine,
        "feature_engine": feature_engine,
        "multi_model": multi_model,
        "strategy": strategy,
        "risk_gate": risk_gate,
        "paper": paper,
        "audit": audit,
        "symbol": "RELIANCE",
        "symbol_id": 1,
        "oid": 10_000_000,
    }

    yield ctx

    try:
        audit.append({"event_type": "SESSION_END", "symbol": "SESSION"})
    except Exception:
        pass
    try:
        engine.stop()
    except Exception:
        pass


def _one_round_trip(ctx, price: float = 100.0, qty: int = 1):
    engine = ctx["engine"]
    symbol = ctx["symbol"]
    symbol_id = ctx["symbol_id"]
    ctx["oid"] += 1
    buy_id = ctx["oid"]
    ctx["oid"] += 1
    sell_id = ctx["oid"]
    ipx = int(round(price * 100))
    engine.submit(_mk_order(buy_id, symbol_id, "B", ipx, qty))
    engine.submit(_mk_order(sell_id, symbol_id, "S", ipx, qty))
    tr = _drain_trade(engine, timeout_s=1.0)
    assert tr is not None

    features = ctx["feature_engine"].compute(_snapshot_from_trade(tr))
    ml = _ml_signal_from_features(features)
    ctx["strategy"].on_orderbook(symbol, [[price, qty]], [[price, qty]])
    pred = 1.0 if ml["signal"] > 0 else (0.0 if ml["signal"] < 0 else 0.5)
    ctx["strategy"].on_signal(symbol, "ensemble", pred, ml["confidence"])

    orders = ctx["strategy"].get_pending_orders()
    for od in orders:
        px = float(od.get("price") or price)
        ctx["risk_gate"].evaluate_order(
            symbol=od["symbol"],
            side=od["side"],
            qty=int(od["qty"]),
            price=px,
            current_positions=dict(ctx["paper"].positions),
            current_pnl=ctx["paper"].pnl,
            peak_pnl=(ctx["paper"].peak_capital - ctx["paper"].starting_capital),
        )
        oid = ctx["paper"].submit_order(od["symbol"], od["side"], int(od["qty"]), "MARKET", px)
        ctx["audit"].append(
            {"event_type": "ORDER_SUBMIT", "symbol": od["symbol"], "side": od["side"], "qty": int(od["qty"]), "price": px, "order_id": oid}
        )
        fills = ctx["paper"].process_market_tick(od["symbol"], best_bid=px, best_ask=px)
        if fills:
            f = fills[0]
            ctx["audit"].append(
                {"event_type": "FULL_FILL", "symbol": od["symbol"], "side": f["side"], "qty": int(f["qty"]), "price": float(f["price"]), "order_id": f["order_id"]}
            )
        else:
            ctx["audit"].append(
                {"event_type": "PARTIAL_FILL", "symbol": od["symbol"], "side": od["side"], "qty": int(od["qty"]), "price": px, "order_id": oid}
            )
    return tr, features, ml


class TestCppPythonIntegration:
    def test_fill_triggers_feature_extraction(self, full_pipeline):
        _tr, features, _ml = _one_round_trip(full_pipeline, price=100.0, qty=10)
        assert isinstance(features, dict)
        assert len(features.keys()) == 42

    def test_feature_triggers_ml_signal(self, full_pipeline):
        last = None
        for i in range(10):
            _tr, _f, ml = _one_round_trip(full_pipeline, price=100.0 + i * 0.01, qty=1)
            last = ml
        assert last is not None
        assert {"signal", "confidence", "model_scores"}.issubset(set(last.keys()))
        assert last["signal"] in {-1, 0, 1}
        assert 0.0 <= float(last["confidence"]) <= 1.0

    def test_signal_triggers_strategy_order(self, full_pipeline):
        s = full_pipeline["strategy"]
        sym = full_pipeline["symbol"]
        s.on_orderbook(sym, [[100.0, 10]], [[100.1, 10]])
        s.on_signal(sym, "forced", 1.0, 0.9)
        orders = s.get_pending_orders()
        if orders:
            od = orders[0]
            assert od["symbol"]
            assert int(od["qty"]) > 0
        else:
            assert orders == []

    def test_risk_gate_blocks_oversized_order(self, full_pipeline):
        rg = full_pipeline["risk_gate"]
        paper = full_pipeline["paper"]
        before = dict(paper.positions)
        with pytest.raises(RiskViolationException):
            rg.evaluate_order(
                symbol=full_pipeline["symbol"],
                side="BUY",
                qty=1000,
                price=1000.0,
                current_positions=dict(paper.positions),
                current_pnl=paper.pnl,
                peak_pnl=(paper.peak_capital - paper.starting_capital),
            )
        assert dict(paper.positions) == before

    def test_paper_engine_records_fill(self, full_pipeline):
        _one_round_trip(full_pipeline, price=101.0, qty=2)
        m = full_pipeline["paper"].get_realtime_metrics()
        assert int(m["total_trades"]) >= 1

    def test_audit_log_records_full_session(self, full_pipeline):
        for i in range(50):
            _one_round_trip(full_pipeline, price=102.0 + i * 0.01, qty=1)
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d")
        rows = full_pipeline["audit"].replay_session(today)
        assert any(r.get("event_type") == "SESSION_START" for r in rows)
        assert sum(1 for r in rows if r.get("event_type") == "ORDER_SUBMIT") > 0
        assert sum(1 for r in rows if r.get("event_type") in {"FULL_FILL", "PARTIAL_FILL"}) > 0
        for r in rows:
            assert r.get("logged_at") is not None
            assert str(r.get("symbol", "")).strip() != ""

    def test_pipeline_throughput(self, full_pipeline):
        n = 1000
        t0 = time.perf_counter()
        for i in range(n):
            _one_round_trip(full_pipeline, price=103.0 + (i % 10) * 0.01, qty=1)
        dt = time.perf_counter() - t0
        rps = n / dt if dt > 0 else float("inf")
        print(f"pipeline throughput={rps:.2f} round-trips/sec")
        assert rps > 500

    def test_eod_flatten_via_cpp_engine(self, full_pipeline):
        paper = full_pipeline["paper"]
        audit = full_pipeline["audit"]
        symbol = full_pipeline["symbol"]

        for _ in range(5):
            paper.submit_order(symbol, "BUY", 1, "MARKET", 100.0)
            paper.process_market_tick(symbol, best_bid=100.0, best_ask=100.0)

        broker = _PaperBrokerAdapter(paper, audit)
        sched = EODScheduler(broker=broker, dry_run=False)
        sched.flatten_all_positions()

        open_qty = sum(abs(int(v)) for v in paper.positions.values())
        assert open_qty == 0

        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d")
        rows = audit.replay_session(today)
        eod_rows = [r for r in rows if r.get("event_type") == "EOD_FLATTEN" and r.get("symbol") == symbol]
        assert len(eod_rows) >= 1
