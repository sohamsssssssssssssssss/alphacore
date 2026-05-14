"""Iceberg order detection engine for NSE order book data.

Detects hidden institutional orders by watching for repeated rapid
refills at the same price level after liquidity is consumed.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from models.schemas import IcebergDetection, OrderBookSnapshot

logger = logging.getLogger(__name__)


class IcebergDetector:
    """Detect repeated refill patterns consistent with iceberg execution.

    A visible clip that repeatedly replenishes after being hit can indicate a
    larger hidden parent order. This engine tracks refill timestamps by symbol
    and price level, escalates confidence as repetitions accumulate, and keeps
    only recently observed icebergs active.
    """

    REFILL_WINDOW_SECONDS: int = 10
    MIN_REFILL_COUNT: int = 3
    HIGH_CONFIDENCE_REFILLS: int = 6
    STALE_DETECTION_MINUTES: int = 5
    TRACKER_RETENTION_SECONDS: int = 60

    def __init__(self) -> None:
        """Initialize refill tracking state."""

        self._refill_tracker: dict[str, dict[tuple[float, str], list[datetime]]] = defaultdict(dict)
        self._active_icebergs: dict[str, list[IcebergDetection]] = defaultdict(list)
        self._prev_snapshots: dict[str, OrderBookSnapshot] = {}
        self._detection_ids: int = 0

    def update(self, symbol: str, snapshot: OrderBookSnapshot) -> list[IcebergDetection]:
        """Detect new or updated iceberg orders for the provided snapshot."""

        normalized_symbol = symbol.upper()
        prev = self._prev_snapshots.get(normalized_symbol)
        self._prev_snapshots[normalized_symbol] = snapshot
        if prev is None:
            return []

        try:
            refills = self._check_refills(normalized_symbol, prev, snapshot)
            now = snapshot.timestamp
            detections: list[IcebergDetection] = []
            for price_level, direction in refills:
                key = (price_level, direction)
                timestamps = self._refill_tracker[normalized_symbol].setdefault(key, [])
                timestamps.append(now)
                window_cutoff = now - timedelta(seconds=self.REFILL_WINDOW_SECONDS)
                timestamps[:] = [ts for ts in timestamps if ts >= window_cutoff]
                refill_count = len(timestamps)
                if refill_count < self.MIN_REFILL_COUNT:
                    continue

                visible_size = self._get_visible_size(snapshot, price_level, direction)
                detection = self._build_detection(
                    normalized_symbol,
                    now,
                    price_level,
                    visible_size,
                    refill_count,
                    direction,
                )
                detections.append(detection)
                logger.info(
                    "Iceberg detected: symbol=%s side=%s price=%.4f refills=%s confidence=%s",
                    normalized_symbol,
                    direction,
                    price_level,
                    refill_count,
                    detection.confidence_score,
                )

            self._merge_active_detections(normalized_symbol, detections)
            self._cleanup_stale(normalized_symbol)
            return detections
        except Exception as exc:
            logger.error("Iceberg detection failed for %s: %s", normalized_symbol, exc)
            return []

    def _check_refills(
        self,
        symbol: str,
        prev: OrderBookSnapshot,
        curr: OrderBookSnapshot,
    ) -> list[tuple[float, str]]:
        """Identify levels where liquidity likely refilled after being consumed."""

        del symbol
        events: list[tuple[float, str]] = []
        prev_bids = {level.price: level.volume for level in prev.bids}
        curr_bids = {level.price: level.volume for level in curr.bids}
        prev_asks = {level.price: level.volume for level in prev.asks}
        curr_asks = {level.price: level.volume for level in curr.asks}

        for price, curr_volume in curr_bids.items():
            prev_volume = prev_bids.get(price)
            if prev_volume is None:
                continue
            if curr_volume >= prev_volume and prev_volume > 0:
                events.append((price, "buy"))

        for price, curr_volume in curr_asks.items():
            prev_volume = prev_asks.get(price)
            if prev_volume is None:
                continue
            if curr_volume >= prev_volume and prev_volume > 0:
                events.append((price, "sell"))

        return events

    def _calculate_confidence(self, refill_count: int) -> int:
        """Map refill count to a confidence score between 0 and 100."""

        mapping = {3: 40, 4: 55, 5: 70, 6: 80, 7: 88}
        if refill_count <= 2:
            return 0
        if refill_count >= 8:
            return 95
        if refill_count in mapping:
            return mapping[refill_count]

        lower = max(level for level in mapping if level < refill_count)
        upper = min(level for level in mapping if level > refill_count)
        lower_score = mapping[lower]
        upper_score = mapping[upper]
        fraction = (refill_count - lower) / (upper - lower)
        return int(round(lower_score + (upper_score - lower_score) * fraction))

    def _estimate_hidden_volume(self, visible_size: float, refill_count: int) -> float:
        """Estimate minimum hidden volume behind the observed visible clips."""

        return round(visible_size * refill_count, 2)

    def get_active_icebergs(self, symbol: str) -> list[IcebergDetection]:
        """Return active iceberg detections for a symbol."""

        self._cleanup_stale(symbol.upper())
        return list(self._active_icebergs.get(symbol.upper(), []))

    def get_all_active_icebergs(self) -> dict[str, list[IcebergDetection]]:
        """Return all currently active iceberg detections grouped by symbol."""

        for symbol in list(self._active_icebergs.keys()):
            self._cleanup_stale(symbol)
        return {symbol: list(detections) for symbol, detections in self._active_icebergs.items()}

    def _cleanup_stale(self, symbol: str) -> None:
        """Remove stale detections and old refill tracker entries."""

        now = datetime.now(timezone.utc)
        normalized_symbol = symbol.upper()
        detection_cutoff = now - timedelta(minutes=self.STALE_DETECTION_MINUTES)
        tracker_cutoff = now - timedelta(seconds=self.TRACKER_RETENTION_SECONDS)

        current = []
        for detection in self._active_icebergs.get(normalized_symbol, []):
            if detection.last_seen_at >= detection_cutoff:
                current.append(detection)
        self._active_icebergs[normalized_symbol] = current

        tracker = self._refill_tracker.get(normalized_symbol, {})
        cleaned: dict[tuple[float, str], list[datetime]] = {}
        for key, timestamps in tracker.items():
            fresh = [ts for ts in timestamps if ts >= tracker_cutoff]
            if fresh:
                cleaned[key] = fresh
        self._refill_tracker[normalized_symbol] = cleaned

    def _get_visible_size(self, snapshot: OrderBookSnapshot, price_level: float, direction: str) -> float:
        """Return the visible volume currently resting at the tracked level."""

        levels = snapshot.bids if direction == "buy" else snapshot.asks
        for level in levels:
            if level.price == price_level:
                return float(level.volume)
        return 0.0

    def _build_detection(
        self,
        symbol: str,
        detected_at: datetime,
        price_level: float,
        visible_size: float,
        refill_count: int,
        direction: str,
    ) -> IcebergDetection:
        """Construct an iceberg detection object."""

        self._detection_ids += 1
        confidence_score = self._calculate_confidence(refill_count)
        return IcebergDetection(
            id=self._detection_ids,
            symbol=symbol,
            detected_at=detected_at,
            price_level=price_level,
            visible_size=round(visible_size, 2),
            estimated_hidden_volume=self._estimate_hidden_volume(visible_size, refill_count),
            refill_count=refill_count,
            direction=direction,
            confidence_score=confidence_score,
            is_active=True,
            last_seen_at=detected_at,
        )

    def _merge_active_detections(self, symbol: str, detections: list[IcebergDetection]) -> None:
        """Merge fresh detections into the active iceberg registry."""

        active = {
            (item.price_level, item.direction): item
            for item in self._active_icebergs.get(symbol, [])
        }
        for detection in detections:
            active[(detection.price_level, detection.direction)] = detection
        self._active_icebergs[symbol] = list(active.values())


iceberg_detector = IcebergDetector()
