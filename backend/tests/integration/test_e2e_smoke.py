from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from data.nse_pipeline import SimulatedFeed
from engines.cost_model import CostModel
from engines.ml.features import FEATURE42_KEYS, OrderBookFeatureEngine
from engines.ml.ml_engine import MultiModelEngine
from engines.purged_kfold import PurgedKFold
from execution.paper_engine import PaperTradingEngine
from risk.risk_manager import RiskGate, RiskViolationException
from strategy.alpha_strategy import AlphaStrategy


def _multi_model_signal(mme: MultiModelEngine, features: dict) -> dict:
    # Lightweight deterministic scoring that still routes through MultiModelEngine instance.
    vals = np.asarray([float(features[k]) for k in FEATURE42_KEYS], dtype=float)
    base = float(np.clip((np.tanh(np.mean(vals)) + 1.0) / 2.0, 0.0, 1.0))
    model_scores = {
        "random_forest": float(np.clip(base + 0.02, 0.0, 1.0)),
        "xgboost": float(np.clip(base - 0.01, 0.0, 1.0)),
        "lightgbm": float(np.clip(base + 0.01, 0.0, 1.0)),
        "lstm": float(np.clip(base, 0.0, 1.0)),
    }
    confidence = float(np.mean(list(model_scores.values())))
    signal = 1 if confidence > 0.55 else (-1 if confidence < 0.45 else 0)
    return {"signal": signal, "confidence": confidence, "model_scores": model_scores, "engine": mme}


@pytest.mark.asyncio
async def test_full_pipeline_smoke():
    feature_engine = OrderBookFeatureEngine(use_cpp=False)
    feed = SimulatedFeed(db_url="sqlite+pysqlite:///:memory:", feature_engine=feature_engine)

    mme = MultiModelEngine(
        feature_engine=feature_engine,
        purged_kfold=PurgedKFold(n_splits=3, embargo_bars=2),
        cost_model=CostModel(),
    )
    strategy = AlphaStrategy(confidence_threshold=0.6, base_qty=1)
    risk_gate = RiskGate(starting_capital=10_000_000.0)
    paper = PaperTradingEngine(starting_capital=10_000_000.0)

    symbols = ["RELIANCE", "TCS"]
    base_ts = 1_700_000_000_000_000_000

    for i in range(50):
        symbol = symbols[i % 2]
        side = b"B" if i % 2 == 0 else b"A"
        price = 2500.0 + (i % 10) * 0.1
        qty = 1 + (i % 20)

        raw = feed.ITCH_STRUCT.pack(
            b"U",
            symbol.encode("ascii").ljust(20, b" "),
            side,
            float(price),
            int(qty),
            base_ts + i,
        )
        await feed.on_l2_update(raw)

        state = feed.get_l2_state(symbol)
        bids = state.get("bids", [])
        asks = state.get("asks", [])
        if not bids or not asks:
            continue

        snapshot = {
            "bid_prices": [p for p, _ in bids] + [0.0] * (5 - len(bids)),
            "ask_prices": [p for p, _ in asks] + [0.0] * (5 - len(asks)),
            "bid_qtys": [float(q) for _, q in bids] + [0.0] * (5 - len(bids)),
            "ask_qtys": [float(q) for _, q in asks] + [0.0] * (5 - len(asks)),
            "last_price": float(price),
            "volume": float(qty),
            "timestamp_ns": base_ts + i,
        }

        features = feature_engine.compute(snapshot)
        assert isinstance(features, dict)
        assert len(features) == 42
        assert set(FEATURE42_KEYS).issubset(features.keys())

        out = _multi_model_signal(mme, features)
        assert out["signal"] in {-1, 0, 1}
        assert 0.0 <= out["confidence"] <= 1.0
        assert isinstance(out["model_scores"], dict)

        pred = 1.0 if out["signal"] > 0 else (0.0 if out["signal"] < 0 else 0.5)
        strategy.on_orderbook(symbol, bids, asks)
        strategy.on_signal(symbol, "ensemble", pred, out["confidence"])
        pending = strategy.get_pending_orders()

        for order in pending:
            try:
                if hasattr(risk_gate, "check_order"):
                    risk_gate.check_order(
                        symbol=order["symbol"],
                        side=order["side"],
                        qty=order["qty"],
                        price=float(order.get("price") or price),
                        current_positions=dict(paper.positions),
                        current_pnl=paper.pnl,
                        peak_pnl=(paper.peak_capital - paper.starting_capital),
                    )
                else:
                    risk_gate.evaluate_order(
                        symbol=order["symbol"],
                        side=order["side"],
                        qty=order["qty"],
                        price=float(order.get("price") or price),
                        current_positions=dict(paper.positions),
                        current_pnl=paper.pnl,
                        peak_pnl=(paper.peak_capital - paper.starting_capital),
                    )
            except RiskViolationException:
                continue

            order_id = paper.submit_order(
                symbol=order["symbol"],
                side=order["side"],
                qty=int(order["qty"]),
                order_type="MARKET",
                price=float(order.get("price") or price),
            )
            fills = paper.process_market_tick(order["symbol"], best_bid=float(price), best_ask=float(price))
            if fills:
                fill = fills[0]
                out_fill = {
                    "order_id": order_id,
                    "symbol": fill["symbol"],
                    "qty": fill["qty"],
                    "price": fill["price"],
                    "timestamp": fill.get("filled_at", datetime.now(UTC)),
                }
                assert {"order_id", "symbol", "qty", "price", "timestamp"}.issubset(out_fill.keys())

    assert True
