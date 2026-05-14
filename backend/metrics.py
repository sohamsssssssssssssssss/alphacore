"""Prometheus metrics definitions for AlphaCore."""

from prometheus_client import Counter, Gauge

# Custom AlphaCore metrics
DETECTIONS_TOTAL = Counter(
    "alphacore_detections_total",
    "Total detections fired",
    ["type", "symbol", "severity"],
)
SIGNALS_TOTAL = Counter(
    "alphacore_signals_total",
    "Total trade signals generated",
    ["symbol", "direction"],
)
ACTIVE_SIGNALS = Gauge(
    "alphacore_active_signals",
    "Currently active signals",
    ["symbol"],
)
ORDER_BOOK_UPDATES = Counter(
    "alphacore_orderbook_updates_total",
    "Total order book updates processed",
    ["symbol"],
)
