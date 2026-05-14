"""Pydantic data models for API and in-memory order book state."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class OrderLevel(BaseModel):
    """Single price level in the order book."""

    price: float
    volume: float


class OrderBookSnapshot(BaseModel):
    """Normalized view of the latest order book snapshot for a symbol."""

    symbol: str
    timestamp: datetime
    bids: list[OrderLevel] = Field(default_factory=list)
    asks: list[OrderLevel] = Field(default_factory=list)
    spread: float
    bid_ask_imbalance: float
    total_bid_volume: float
    total_ask_volume: float
    stale: bool = False


class NarrativeSignal(BaseModel):
    """Incoming narrative signal payload."""

    narrative: str
    confidence: str
    strength: str | None = None
    regime: str
    started: str | None = None


class NarrativeSignalResponse(BaseModel):
    """Persisted narrative signal representation."""

    id: int
    received_at: datetime
    narrative: str
    confidence: str
    strength: str | None = None
    regime: str
    started: str | None = None


class IcebergDetection(BaseModel):
    """Detected iceberg order metadata."""

    id: int
    symbol: str
    detected_at: datetime
    price_level: float
    visible_size: float
    estimated_hidden_volume: float
    refill_count: int
    direction: str
    confidence_score: int
    is_active: bool
    last_seen_at: datetime


class SpoofDetection(BaseModel):
    """Detected spoofing alert details."""

    id: int
    symbol: str
    detected_at: datetime
    order_price: float
    order_size: float
    spoof_score: int
    severity: str
    time_active_seconds: int
    price_impact: float | None = None
    counter_trade_detected: bool
    check_refill_score: int | None = None
    check_cancel_speed_score: int | None = None
    check_fill_ratio_score: int | None = None
    check_price_impact_score: int | None = None
    check_counter_trade_score: int | None = None


class FlowImbalance(BaseModel):
    """Current or historical order flow imbalance reading."""

    symbol: str
    timestamp: datetime
    imbalance_score: float
    aggressive_buys: float
    aggressive_sells: float
    window_minutes: int


class HeatmapCell(BaseModel):
    """Single heatmap cell for one price level at one time."""

    price_level: float
    bid_volume: float
    ask_volume: float
    total_volume: float
    timestamp: datetime


class HeatmapResponse(BaseModel):
    """Heatmap payload for a symbol and time window."""

    symbol: str
    generated_at: datetime
    cells: list[HeatmapCell]
    price_min: float
    price_max: float
    time_window_minutes: int


class HeatmapMatrixResponse(BaseModel):
    """Frontend-ready heatmap matrix response."""

    symbol: str
    matrix: list[list[float]]
    price_levels: list[str]
    time_labels: list[str]
    max_volume: float


class DetectionSummary(BaseModel):
    """Aggregate summary of active detections and flow."""

    total_icebergs: int
    total_spoof: int
    high_severity_spoof: int
    medium_severity_spoof: int
    low_severity_spoof: int
    symbols_with_icebergs: list[str]
    symbols_with_spoof: list[str]


class NarrativeSignalInput(BaseModel):
    """NarrativeEdge signal intake payload."""

    narrative: str
    confidence: str
    strength: str | None = None
    regime: str
    started: str | None = None


class HealthResponse(BaseModel):
    """Health and liveness response for the backend."""

    status: str
    database: str
    scheduler: str
    kill_switch: bool
    circuit_breakers_active: int
    journal_events: int
    last_journal_event: str | None
    uptime_seconds: int


class SymbolStatus(BaseModel):
    """Status payload for a tracked symbol."""

    symbol: str
    last_update: datetime | None


class TradeSignal(BaseModel):
    """Directional trade signal generated from AlphaCore detections."""

    id: int
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    target_price: float
    confidence: int
    score: int
    reasons: list[str]
    generated_at: datetime
