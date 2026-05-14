"""Spoofing detection engine for NSE order book data.

Detects manipulative large orders that appear to influence price and then
cancel quickly without meaningful execution, using a five-check scoring model.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean

from models.schemas import OrderBookSnapshot, SpoofDetection

logger = logging.getLogger(__name__)


class SpoofDetector:
    """Score suspicious large-order cancellations for spoofing behaviour.

    The engine tracks large displayed orders, then evaluates whether they
    disappear quickly, fill minimally, move price, and reverse after cancel.
    Each suspicious feature contributes to a cumulative spoof score.
    """

    # Tuned so the detector still produces alerts against AlphaCore's mock
    # after-hours depth while remaining selective on normal quote noise.
    LARGE_ORDER_THRESHOLD: float = 100.0
    CANCEL_WINDOW_SECONDS: int = 30
    HIGH_CONFIDENCE_THRESHOLD: int = 70
    MIN_REPORT_SCORE: int = 30
    MAX_ALERTS_PER_SYMBOL: int = 100

    def __init__(self) -> None:
        """Initialize spoof tracking state."""

        self._large_order_tracker: dict[str, dict[tuple[float, str], dict]] = defaultdict(dict)
        self._prev_snapshots: dict[str, OrderBookSnapshot] = {}
        self._active_spoof_alerts: dict[str, list[SpoofDetection]] = defaultdict(list)
        self._repeat_counts: dict[str, dict[tuple[float, str], int]] = defaultdict(dict)
        self._detection_ids: int = 0

    def update(self, symbol: str, snapshot: OrderBookSnapshot) -> list[SpoofDetection]:
        """Track large orders and score suspicious cancellations for spoofing."""

        normalized_symbol = symbol.upper()
        prev = self._prev_snapshots.get(normalized_symbol)
        self._prev_snapshots[normalized_symbol] = snapshot
        if prev is None:
            return []

        try:
            self._detect_new_large_orders(normalized_symbol, prev, snapshot)
            cancellation_events = self._detect_cancellations(normalized_symbol, prev, snapshot)
            detections: list[SpoofDetection] = []
            for event in cancellation_events:
                detection = self._score_cancellation(normalized_symbol, event, snapshot)
                if detection.spoof_score >= self.MIN_REPORT_SCORE:
                    detections.append(detection)
                    self._active_spoof_alerts[normalized_symbol].append(detection)
                    self._active_spoof_alerts[normalized_symbol] = self._active_spoof_alerts[
                        normalized_symbol
                    ][-self.MAX_ALERTS_PER_SYMBOL :]
                    logger.info(
                        "Spoof alert: symbol=%s side=%s price=%.4f score=%s severity=%s",
                        normalized_symbol,
                        event["direction"],
                        event["order_price"],
                        detection.spoof_score,
                        detection.severity,
                    )
            return detections
        except Exception as exc:
            logger.error("Spoof detection failed for %s: %s", normalized_symbol, exc)
            return []

    def _detect_new_large_orders(
        self,
        symbol: str,
        prev: OrderBookSnapshot,
        curr: OrderBookSnapshot,
    ) -> None:
        """Start tracking new large displayed orders that appeared this tick."""

        prev_bids = {level.price: level.volume for level in prev.bids}
        prev_asks = {level.price: level.volume for level in prev.asks}

        for level in curr.bids:
            prev_volume = prev_bids.get(level.price, 0.0)
            increase = level.volume - prev_volume
            if increase > self.LARGE_ORDER_THRESHOLD:
                self._large_order_tracker[symbol][(level.price, "buy")] = {
                    "size": float(level.volume),
                    "appeared_at": curr.timestamp,
                    "price_at_appear": self._mid_price(curr),
                    "direction": "buy",
                    "current_price": self._mid_price(curr),
                    "initial_volume": float(level.volume),
                }

        for level in curr.asks:
            prev_volume = prev_asks.get(level.price, 0.0)
            increase = level.volume - prev_volume
            if increase > self.LARGE_ORDER_THRESHOLD:
                self._large_order_tracker[symbol][(level.price, "sell")] = {
                    "size": float(level.volume),
                    "appeared_at": curr.timestamp,
                    "price_at_appear": self._mid_price(curr),
                    "direction": "sell",
                    "current_price": self._mid_price(curr),
                    "initial_volume": float(level.volume),
                }

    def _detect_cancellations(
        self,
        symbol: str,
        prev: OrderBookSnapshot,
        curr: OrderBookSnapshot,
    ) -> list[dict]:
        """Find tracked large orders that were removed quickly and score them."""

        curr_bids = {level.price: level.volume for level in curr.bids}
        curr_asks = {level.price: level.volume for level in curr.asks}
        events: list[dict] = []

        for key, tracked in list(self._large_order_tracker.get(symbol, {}).items()):
            price, direction = key
            current_volume = curr_bids.get(price, 0.0) if direction == "buy" else curr_asks.get(price, 0.0)
            previous_volume = next(
                (
                    level.volume
                    for level in (prev.bids if direction == "buy" else prev.asks)
                    if level.price == price
                ),
                0.0,
            )
            if current_volume >= previous_volume:
                tracked["current_price"] = self._mid_price(curr)
                continue

            time_active = max(0, int((curr.timestamp - tracked["appeared_at"]).total_seconds()))
            if time_active > self.CANCEL_WINDOW_SECONDS and current_volume > 0:
                continue

            filled_volume = max(0.0, tracked["size"] - current_volume)
            event = {
                "order_price": price,
                "order_size": float(tracked["size"]),
                "direction": direction,
                "appeared_at": tracked["appeared_at"],
                "time_active_seconds": time_active,
                "filled_volume": round(filled_volume, 2),
                "price_at_appear": float(tracked["price_at_appear"]),
                "current_mid_price": self._mid_price(curr),
            }
            events.append(event)
            self._large_order_tracker[symbol].pop(key, None)

        return events

    def _score_cancellation(
        self,
        symbol: str,
        event: dict,
        curr: OrderBookSnapshot,
    ) -> SpoofDetection:
        """Run the five-check spoof scoring model for one cancellation event."""

        cancel_speed_score = self._score_cancel_speed(event["time_active_seconds"])
        fill_ratio = event["filled_volume"] / event["order_size"] if event["order_size"] else 0.0
        fill_ratio_score = self._score_fill_ratio(fill_ratio)
        price_impact = self._price_change_pct(event["price_at_appear"], event["current_mid_price"])
        price_impact_score = self._score_price_impact(abs(price_impact))
        counter_trade_detected = abs(price_impact) >= 0.2
        counter_trade_score = 20 if abs(price_impact) >= 0.2 else 10 if abs(price_impact) >= 0.1 else 0
        repeat_score = self._score_repeat(symbol, event["order_price"], event["direction"])
        total_score = min(
            100,
            cancel_speed_score + fill_ratio_score + price_impact_score + counter_trade_score + repeat_score,
        )
        severity = self._severity(total_score)

        self._detection_ids += 1
        return SpoofDetection(
            id=self._detection_ids,
            symbol=symbol,
            detected_at=curr.timestamp,
            order_price=event["order_price"],
            order_size=event["order_size"],
            spoof_score=total_score,
            severity=severity,
            time_active_seconds=event["time_active_seconds"],
            price_impact=round(price_impact, 4),
            counter_trade_detected=counter_trade_detected,
            check_refill_score=repeat_score,
            check_cancel_speed_score=cancel_speed_score,
            check_fill_ratio_score=fill_ratio_score,
            check_price_impact_score=price_impact_score,
            check_counter_trade_score=counter_trade_score,
        )

    def get_active_spoof_alerts(self, symbol: str) -> list[SpoofDetection]:
        """Return spoof alerts stored for a symbol."""

        return list(self._active_spoof_alerts.get(symbol.upper(), []))

    def get_all_spoof_alerts(self) -> dict[str, list[SpoofDetection]]:
        """Return spoof alerts for all symbols."""

        return {symbol: list(alerts) for symbol, alerts in self._active_spoof_alerts.items()}

    def _score_cancel_speed(self, time_active_seconds: int) -> int:
        """Score how quickly a large order was cancelled."""

        if time_active_seconds <= 5:
            return 20
        if time_active_seconds <= 15:
            return 15
        if time_active_seconds <= 30:
            return 10
        return 5

    def _score_fill_ratio(self, fill_ratio: float) -> int:
        """Score how little of the large order appears to have traded."""

        if fill_ratio < 0.05:
            return 20
        if fill_ratio <= 0.20:
            return 10
        return 0

    def _score_price_impact(self, price_impact_pct: float) -> int:
        """Score the apparent price impact of the displayed large order."""

        if price_impact_pct > 0.3:
            return 20
        if price_impact_pct >= 0.1:
            return 10
        if price_impact_pct > 0:
            return 5
        return 0

    def _score_repeat(self, symbol: str, price: float, direction: str) -> int:
        """Score repeated suspicious activity at the same level."""

        key = (price, direction)
        current = self._repeat_counts[symbol].get(key, 0) + 1
        self._repeat_counts[symbol][key] = current
        if current >= 3:
            return 20
        if current == 2:
            return 10
        return 0

    def _severity(self, total_score: int) -> str:
        """Map spoof score to severity label."""

        if total_score >= self.HIGH_CONFIDENCE_THRESHOLD:
            return "HIGH"
        if total_score >= 40:
            return "MEDIUM"
        return "LOW"

    def _mid_price(self, snapshot: OrderBookSnapshot) -> float:
        """Return the current mid price for a snapshot."""

        if snapshot.bids and snapshot.asks:
            return round((snapshot.bids[0].price + snapshot.asks[0].price) / 2, 4)
        if snapshot.bids:
            return snapshot.bids[0].price
        if snapshot.asks:
            return snapshot.asks[0].price
        return 0.0

    def _price_change_pct(self, start_price: float, end_price: float) -> float:
        """Return percentage mid-price change between two points."""

        if start_price == 0:
            return 0.0
        return ((end_price - start_price) / start_price) * 100.0


spoof_detector = SpoofDetector()
