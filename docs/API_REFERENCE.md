# API Reference

This document reflects the live AlphaCore backend response shapes currently exposed on `http://localhost:8000`.

## GET `/api/health`

Health and liveness information.

Example request:

```bash
curl http://localhost:8000/api/health
```

Example response:

```json
{
  "status": "ok",
  "timestamp": "2026-05-14T01:46:12.345678Z",
  "nse_connected": true,
  "active_symbols": ["HDFCBANK", "ICICIBANK", "INFY", "RELIANCE", "TCS"],
  "last_data_fetch": "2026-05-14T01:45:56.719452Z",
  "db_connected": true
}
```

## GET `/api/orderbook/{symbol}`

Latest normalized order book snapshot.

Example request:

```bash
curl http://localhost:8000/api/orderbook/RELIANCE
```

Example response:

```json
{
  "symbol": "RELIANCE",
  "timestamp": "2026-05-13T19:01:39.249250Z",
  "bids": [
    { "price": 2890.0, "volume": 793.0 }
  ],
  "asks": [
    { "price": 2890.87, "volume": 682.0 }
  ],
  "spread": 0.87,
  "bid_ask_imbalance": 0.358717,
  "total_bid_volume": 7797.0,
  "total_ask_volume": 3680.0,
  "stale": true
}
```

## GET `/api/orderbook/{symbol}/history`

Historical snapshots for a symbol.

Example request:

```bash
curl "http://localhost:8000/api/orderbook/RELIANCE/history?minutes=30"
```

Example response:

```json
[
  {
    "symbol": "RELIANCE",
    "timestamp": "2026-05-14T01:34:05.315743Z",
    "bids": [{ "price": 2890.0, "volume": 498.0 }],
    "asks": [{ "price": 2890.87, "volume": 1575.0 }],
    "spread": 0.87,
    "bid_ask_imbalance": -0.135329,
    "total_bid_volume": 9287.0,
    "total_ask_volume": 12168.0,
    "stale": false
  }
]
```

## WS `/ws/orderbook/{symbol}`

Live WebSocket stream of order book updates.

Example connect:

```text
ws://localhost:8000/ws/orderbook/RELIANCE
```

Example frame:

```json
{
  "type": "orderbook_update",
  "symbol": "RELIANCE",
  "timestamp": "2026-05-14T01:45:56.719452Z",
  "bids": [{ "price": 2890.0, "volume": 1011.0 }],
  "asks": [{ "price": 2890.87, "volume": 875.0 }],
  "spread": 0.87,
  "bid_ask_imbalance": 0.022611,
  "total_bid_volume": 6083.0,
  "total_ask_volume": 5814.0
}
```

## GET `/api/detections/icebergs`

Persisted iceberg detections from PostgreSQL.

Example request:

```bash
curl http://localhost:8000/api/detections/icebergs
```

Example response:

```json
[
  {
    "id": 100,
    "symbol": "ICICIBANK",
    "detected_at": "2026-05-13T19:40:12.228257Z",
    "price_level": 1241.85,
    "visible_size": 1641.0,
    "estimated_hidden_volume": 4923.0,
    "refill_count": 3,
    "direction": "sell",
    "confidence_score": 40,
    "is_active": true,
    "last_seen_at": "2026-05-13T19:40:12.228257Z"
  }
]
```

## GET `/api/detections/spoof`

Persisted spoof alerts from PostgreSQL.

Example request:

```bash
curl http://localhost:8000/api/detections/spoof
```

Example response:

```json
[
  {
    "id": 55,
    "symbol": "ICICIBANK",
    "detected_at": "2026-05-14T02:33:46.057632Z",
    "order_price": 1241.85,
    "order_size": 1942.0,
    "spoof_score": 30,
    "severity": "LOW",
    "time_active_seconds": 29,
    "price_impact": 0.0,
    "counter_trade_detected": false,
    "check_refill_score": 20,
    "check_cancel_speed_score": 10,
    "check_fill_ratio_score": 0,
    "check_price_impact_score": 0,
    "check_counter_trade_score": 0
  }
]
```

## GET `/api/detections/summary`

Detection counts and symbol breakdown from the database.

Example request:

```bash
curl http://localhost:8000/api/detections/summary
```

Example response:

```json
{
  "total_icebergs": 150,
  "total_spoof": 89,
  "high_severity_spoof": 0,
  "medium_severity_spoof": 20,
  "low_severity_spoof": 69,
  "symbols_with_icebergs": ["HDFCBANK", "ICICIBANK", "INFY", "RELIANCE", "TCS"],
  "symbols_with_spoof": ["HDFCBANK", "ICICIBANK", "INFY", "RELIANCE", "TCS"]
}
```

## GET `/api/flow/{symbol}`

Current order flow imbalance.

Example request:

```bash
curl http://localhost:8000/api/flow/RELIANCE
```

Example response:

```json
{
  "symbol": "RELIANCE",
  "timestamp": "2026-05-13T19:40:10.315743Z",
  "imbalance_score": 0.0,
  "aggressive_buys": 0.0,
  "aggressive_sells": 0.0,
  "window_minutes": 1
}
```

## GET `/api/heatmap/{symbol}`

Frontend-ready liquidity heatmap matrix.

Example request:

```bash
curl http://localhost:8000/api/heatmap/RELIANCE
```

Example response:

```json
{
  "symbol": "RELIANCE",
  "matrix": [
    [498.0, 1906.0, 1639.0],
    [1470.0, 1867.0, 1214.0]
  ],
  "price_levels": ["2894.35", "2893.48"],
  "time_labels": ["01:34:05", "01:34:19", "01:34:56"],
  "max_volume": 1959.0
}
```

## POST `/api/narrative/signal`

Insert a NarrativeEdge regime signal.

Example request:

```bash
curl -X POST http://localhost:8000/api/narrative/signal \
  -H "Content-Type: application/json" \
  -d '{
    "narrative": "Rate Hike Fears",
    "confidence": "High",
    "strength": "Building",
    "regime": "rate_hike",
    "started": "2026-05-14"
  }'
```

Example response:

```json
{
  "id": 1,
  "received_at": "2026-05-14T01:45:34.516860Z",
  "narrative": "Rate Hike Fears",
  "confidence": "High",
  "strength": "Building",
  "regime": "rate_hike",
  "started": "2026-05-14"
}
```

## GET `/api/narrative/current`

Most recent active narrative signal.

Example request:

```bash
curl http://localhost:8000/api/narrative/current
```

Example response:

```json
{
  "id": 1,
  "received_at": "2026-05-14T01:45:34.516860Z",
  "narrative": "Rate Hike Fears",
  "confidence": "High",
  "strength": "Building",
  "regime": "rate_hike",
  "started": "2026-05-14"
}
```
