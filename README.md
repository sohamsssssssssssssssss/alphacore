# AlphaCore — Order Book Intelligence Engine

![Python 3.11](https://img.shields.io/badge/Python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688)
![React](https://img.shields.io/badge/React-19-61dafb)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-336791)
![NSE Live Data](https://img.shields.io/badge/NSE-Live%20Data-00d395)
![MIT License](https://img.shields.io/badge/License-MIT-green)

## What This Is

AlphaCore is an order book intelligence system for NSE Indian markets. It ingests real market data, runs detection algorithms on the order book in real time, and visualizes everything in a live React dashboard.

## Dashboard

![Dashboard](docs/dashboard.png)

The dashboard shows live L2 depth, flow imbalance, iceberg detections, spoof alerts, a liquidity heatmap, and narrative regime context in one terminal-style view. It is designed for dense operator visibility rather than generic UI polish.

## Benchmark Results
> Tested at 500 concurrent users on Apple M-series, Python 3.14, PostgreSQL local

### Raw Numbers
Full benchmark report: [`benchmarks/results.md`](benchmarks/results.md)

## Performance

### C Extension Benchmark (`backend/benchmarks/bench_c_ext.py`)

- Python order book (`mid_price`): `22.442 ms` avg
- C extension order book (`mid_price`): `332.842 ms` avg
- Speedup: `0.07x`
- Python iceberg scan: `17.177 ms` avg
- C extension iceberg scan: `66.115 ms` avg
- Speedup: `0.26x`

Current C path is functionally correct but not yet faster due to high Python↔ctypes call overhead per operation and repeated clear/insert loops in benchmark setup. Next optimisation path:
1. Batch insert API in C to reduce call crossings.
2. Keep C order book state warm across iterations.
3. Move benchmark hot loop fully into C-exported function.

## Detection Algorithms

### Iceberg Detection

AlphaCore’s iceberg detector watches the same price level across consecutive order book updates and looks for visible liquidity that keeps refilling after being consumed. When the same bid or ask replenishes repeatedly inside a short time window, the engine increments a refill counter and interprets that pattern as potential hidden parent liquidity. Confidence rises as the refill count rises, and the detector estimates hidden size by multiplying the visible clip by the observed refill count. Each emitted signal includes `symbol`, `price`, `side`, `estimated_hidden_volume`, `confidence` from `0-100`, and `refill_count`. The result is not just “this order type exists”, but “this level is behaving like institutional accumulation or distribution”.

### Spoofing Detection

The spoof detector uses a five-check scoring model rather than a single heuristic. It flags large displayed orders, measures how fast they disappear, evaluates their fill ratio, measures their price impact while they were visible, and checks for counter-trade style behaviour after cancellation. Those sub-scores combine into a `spoof_score` and severity bucket. Alerts are labeled `HIGH`, `MEDIUM`, or `LOW` based on the aggregate score. This makes the output explainable: operators can see why a large order looks manipulative instead of treating spoofing as a black-box guess.

## Architecture

```text
NSE Market Data
     |
NSEFetcher (jugaad-trader + direct scraping)
     |
OrderBookStateManager
     |
┌────┼────┬────────┐
│    │    │        │
Iceberg Spoof Flow Heatmap
Detector Detector Engine Engine
│    │    │        │
└────┴────┴────────┘
     |
PostgreSQL
     |
FastAPI REST + WebSocket
     |
React Dashboard
```

## Tech Stack

| Backend | Frontend |
|---|---|
| Python 3.11 | React 19 |
| FastAPI | Vite |
| PostgreSQL | D3.js |
| SQLAlchemy | Recharts |
| APScheduler | lucide-react |
| jugaad-trader |  |
| nsetools |  |
| pandas |  |
| numpy |  |

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | /api/orderbook/{symbol} | Live L2 order book snapshot |
| GET | /api/orderbook/{symbol}/history | Historical snapshots |
| WS | /ws/orderbook/{symbol} | Live WebSocket stream |
| GET | /api/detections/icebergs | Active iceberg detections |
| GET | /api/detections/spoof | Spoof detection alerts |
| GET | /api/detections/summary | Detection counts + breakdown |
| GET | /api/flow/{symbol} | Order flow imbalance score |
| GET | /api/heatmap/{symbol} | Liquidity heatmap matrix |
| POST | /api/narrative/signal | Receive NarrativeEdge signal |
| GET | /api/narrative/current | Current active regime |
| GET | /api/health | System health check |

## Setup

1. Clone the repo.
2. Create a virtual environment and install dependencies.

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. Create `.env` from `.env.example` and fill in `DATABASE_URL`.
4. Create the PostgreSQL database.

```bash
createdb alphacore
```

5. Start the backend.

```bash
../venv/bin/python3 -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

6. In a new terminal, start the frontend.

```bash
cd frontend
npm install
npm run dev
```

7. Open `http://localhost:5173`.

## Project Context

AlphaCore is Phase 1 of a larger system. The current layer turns raw order book behaviour into structured microstructure signals such as iceberg accumulation, flow imbalance, spoof activity, and liquidity concentration. Those signals are intended to feed AlphaCore’s next-stage alpha engine, which will fuse them with macro and regime context coming from NarrativeEdge. V1 is the intelligence layer; V2 adds the conviction-scored decision layer above it.

## License

MIT
