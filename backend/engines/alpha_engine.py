"""Alpha signal engine combining detections into trade ideas."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

import sqlalchemy as sa

from database import get_database, iceberg_detections, order_book_snapshots, spoof_detections
from metrics import SIGNALS_TOTAL
from engines.risk_limits import risk_limits

logger = logging.getLogger(__name__)


class AlphaEngine:
    """Generate directional trade signals from recent microstructure detections."""

    async def generate_signal(self, symbol: str) -> dict | None:
        normalized_symbol = symbol.upper()
        database = get_database()

        latest_snapshot = await database.fetch_one(
            sa.select(order_book_snapshots)
            .where(order_book_snapshots.c.symbol == normalized_symbol)
            .order_by(order_book_snapshots.c.timestamp.desc(), order_book_snapshots.c.id.desc())
            .limit(1)
        )
        if latest_snapshot is None:
            return None

        iceberg_rows = await database.fetch_all(
            sa.select(iceberg_detections)
            .where(iceberg_detections.c.symbol == normalized_symbol)
            .order_by(iceberg_detections.c.detected_at.desc(), iceberg_detections.c.id.desc())
            .limit(10)
        )
        spoof_rows = await database.fetch_all(
            sa.select(spoof_detections)
            .where(spoof_detections.c.symbol == normalized_symbol)
            .order_by(spoof_detections.c.detected_at.desc(), spoof_detections.c.id.desc())
            .limit(10)
        )

        bids = latest_snapshot["bids"] or []
        asks = latest_snapshot["asks"] or []
        if not bids and not asks:
            return None

        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None
        if best_bid is not None and best_ask is not None:
            mid_price = (best_bid + best_ask) / 2.0
        else:
            mid_price = best_bid if best_bid is not None else best_ask
        if mid_price is None:
            return None

        reasons: list[str] = []
        score = 0

        for row in iceberg_rows:
            direction = (row["direction"] or "").lower()
            if direction == "buy":
                score += 10
                reasons.append("Iceberg buy pressure")
            elif direction == "sell":
                score -= 10
                reasons.append("Iceberg sell pressure")

        # Spoof table currently does not store explicit side, so infer side by price vs mid.
        for row in spoof_rows:
            order_price = float(row["order_price"])
            inferred_side = "buy" if order_price <= mid_price else "sell"
            if inferred_side == "buy":
                score -= 8
                reasons.append("Spoof buy wall detected")
            else:
                score += 8
                reasons.append("Spoof sell wall detected")

        imbalance = float(latest_snapshot["bid_ask_imbalance"] or 0.0)
        if imbalance > 0.3:
            score += 15
            reasons.append("Bid/ask imbalance above +0.3")
        elif imbalance < -0.3:
            score -= 15
            reasons.append("Bid/ask imbalance below -0.3")

        if -20 <= score <= 20:
            return None

        direction = "BUY" if score > 20 else "SELL"
        if direction == "BUY":
            if best_bid is None:
                return None
            entry_price = best_bid
            stop_loss = entry_price * 0.995
            target_price = entry_price * 1.015
        else:
            if best_ask is None:
                return None
            entry_price = best_ask
            stop_loss = entry_price * 1.005
            target_price = entry_price * 0.985

        confidence = min(100, abs(int(score)))
        allowed, reason = risk_limits.check_signal(normalized_symbol, entry_price)
        if not allowed:
            logger.warning("Risk limits blocked signal for %s: %s", normalized_symbol, reason)
            return None

        SIGNALS_TOTAL.labels(symbol=normalized_symbol, direction=direction).inc()

        return {
            "symbol": normalized_symbol,
            "direction": direction,
            "entry_price": round(entry_price, 4),
            "stop_loss": round(stop_loss, 4),
            "target_price": round(target_price, 4),
            "confidence": confidence,
            "score": int(score),
            "reasons": reasons,
            "generated_at": datetime.now(timezone.utc),
        }


alpha_engine = AlphaEngine()
