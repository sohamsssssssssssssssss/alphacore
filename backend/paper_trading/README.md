# AlphaCore — Upstox Sandbox Paper-Trading Harness

Cost-model validation for the locked 49-symbol K=1 cross-sectional strategy.
This harness submits the locked strategy's orders through **Upstox's SANDBOX
environment only** and measures realized execution cost (slippage) vs. the
cost-per-trade assumption in the backtests.

**The strategy is locked. Do not change signal, lookback (20), K (1),
rebalance cadence (21 trading days), or the 49-symbol universe.** The only
thing under test is execution cost.

See `PAPER_TRADING_LOG.md` (repo root) for the experiment's living log.

## Hard safety rules

- Orders go ONLY to `https://sandbox.upstox.com`. `config.sandbox_url()`
  refuses to run if `PAPER_SANDBOX_URL` is anything else, and every
  order-mutating call re-asserts the host.
- The sandbox token is used only for sandbox endpoints; the market-data token
  is used only for read-only live endpoints (quotes/candles/status). Neither
  is ever used for the other's purpose.
- Nothing in this harness can place a live order: `MarketDataClient` has no
  order methods, and `OrderClient` refuses non-sandbox hosts.

## Requirements

- macOS Apple Silicon, `python3.11` (repo convention).
- `requests` (already in repo `requirements.txt`).
- Sandbox app + token: https://account.upstox.com/developer/apps#sandbox
- Read-only market-data token (see below).

## Setup (one time)

```bash
python3.11 backend/paper_trading/scripts/paper_setup.py
# -> follow the printed steps to get the sandbox token + market-data token
cp backend/paper_trading/.env.example backend/paper_trading/.env
# fill in the two tokens
python3.11 backend/paper_trading/scripts/verify_connectivity.py
```

### Market data token — important

Upstox sandbox provides **no market data** (verified in Step 0 of the log).
Live quotes are fetched from the read-only live market-data API. Best option:
the **Analytics token** from your live app (read-only, ~1 year validity,
cannot place orders). A live OAuth token also works but expires daily at
3:30 AM IST. Read-only quoting never touches capital.

### Token expiry

Sandbox tokens are valid **30 days** and have **no refresh flow** (Upstox
sandbox has no token-refresh API — verified). The scheduler detects expiry,
alerts (log + optional Slack), and suppresses orders until a fresh token is
provided. Hot reload: edit `backend/paper_trading/.env` or
`states/paper_trading/tokens.json` while the scheduler runs; it picks the new
token up within one cycle. No restart needed.

## Run

```bash
# dry-run (signal + plan only, no network, no orders):
python3.11 backend/paper_trading/scheduler.py --dry-run

# live paper run (sandbox orders):
python3.11 backend/paper_trading/scheduler.py
```

The scheduler must keep running during market hours (it captures daily closes
at ~15:32 IST and rebalances at ~15:10–15:20 IST on rebalance days). It
recovers from restarts: unresolved orders are reconciled on the next boot.

## Ops commands

```bash
# status anytime (works without the scheduler running):
python3.11 backend/paper_trading/scripts/paper_status.py

# kill switch (clean stop at next cycle boundary):
python3.11 backend/paper_trading/scripts/paper_stop.py
# restart: rm states/paper_trading/KILL && re-run the scheduler

# verify the ported signal matches backtest math:
python3.11 backend/paper_trading/scripts/verify_port.py
```

## Data & files

| Path | Contents |
|---|---|
| `states/paper_trading/logs/events.jsonl` | append-only event log (orders, fills, slippage, errors) |
| `states/paper_trading/state.json` | equity, positions, rebalance bookkeeping |
| `states/paper_trading/close_history.json` | daily closes (seeded from repo CSVs, extended by capture) |
| `states/paper_trading/instruments.json` | symbol -> instrument key cache |
| `states/paper_trading/tokens.json` | hot-reloadable token store |
| `states/paper_trading/KILL` | kill switch file |
| `backend/paper_trading/.env` | credentials (gitignored) |

All runtime state lives under `states/paper_trading/` (gitignored).

## How the cost comparison works

Per trade the harness records (event type `trade`):

- `ref_mid` — live bid/ask midpoint at order submission
- `fill_price` / `fill_source` — sandbox-reported average price, or
  `live_quote_fallback` (live ask/bid) if the sandbox never reports a fill
- `slippage_bps` — realized adverse slippage vs `ref_mid`
- `spread_bps_live` — live quoted spread at submission
- `modeled_cost_rs` — what the backtest cost model
  (`backend/engines/cost_model.py`) would have charged for the same trade

The status script reports the running comparison. **Honesty rule:** if
sandbox fills turn out to be dummy/static prices (checked via the fill-sanity
events), the sandbox cannot validate the cost model as designed — that
limitation is reported plainly in `PAPER_TRADING_LOG.md` rather than
stretched into a conclusion.
