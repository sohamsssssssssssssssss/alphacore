# AlphaCore Paper-Trading Validation Log — Upstox Sandbox

**Status: HARNESS BUILT — awaiting credentials to go live** (2026-08-01)

## Purpose

Nine backtested configurations on the AlphaCore NIFTY dataset failed to show a
statistically significant, cost-surviving edge. The one partial exception is
the **49-symbol, K=1, daily-bar (21-trading-day rebalance) configuration**,
whose 95% Sharpe CI is **[-3.14, +0.05]** — negative in mean, but the upper
bound sits just above zero. The question this experiment answers:

> Is the backtest cost model too pessimistic? Does real-world execution cost
> (as observed through Upstox's sandbox order lifecycle) differ meaningfully
> from the cost-per-trade assumption baked into the backtests?

This is a **cost-model validation**, not a signal search. The strategy
(signal, lookback 20, K=1, 21-trading-day rebalance, 49-symbol universe) is
locked and must not change. **Sandbox only — no live orders, ever.**

## Locked configuration (from UNIVERSE_EXPANSION_EXPERIMENT / K_EXPANSION)

| Parameter | Value |
|---|---|
| Signal | cross-sectional relative strength, trailing 20-day return, ranked |
| K | 1 long + 1 short |
| Rebalance | every 21 captured trading days (~monthly), orders ~15:10–15:20 IST |
| Universe | 49 NIFTY-50 symbols (TATAMOTORS excluded — empty yfinance data) |
| Position size | 10% of equity per leg, floored to whole shares |
| Backtest result | Sharpe -1.57, 95% CI [-3.14, +0.05], net PnL -₹7,474.37, 68 trades, costs ₹4,297.33 (135% cost drag) |
| Backtest cost model | `backend/engines/cost_model.py`: impact k=0.0015 (ADV=qty fallback) + half-spread (High-Low est, clamped [0.5, 50] bps) + ₹20/trade + 0.1% STT on sells; no borrow cost |

## Step 0 — Sandbox capability findings (2026-08-01, official docs)

**Sandbox provides:**
- Order lifecycle only: place/modify/cancel (v2 & v3) on `https://sandbox.upstox.com`.
  Orders stay active 24h; APIs available 24/7; validation identical to live; no funds needed.
- Order book / order details / order history retrieval (announcement: "same fidelity as live").
- Separate sandbox app + access token (one per user), generated at
  account.upstox.com/developer/apps#sandbox, valid **30 days**, exclusively for sandbox.

**Sandbox does NOT provide (built in-house):**
- **No market data.** No sandbox quote/feed endpoints exist. Live read-only
  market-data API is used instead (quotes/candles/status — read-only, no capital risk).
- **No token refresh flow.** Sandbox tokens are static 30-day bearer tokens.
  Harness detects expiry, alerts, and hot-reloads a fresh token without restart.
- **Undocumented fill behavior.** Upstox documents no simulated matching
  engine and no fill-price semantics; orders "remain active for a full
  24-hour cycle". It is unknown without testing whether orders complete and,
  if so, at meaningful prices.

**Consequence (honest design):** every order records the live bid/ask midpoint
at submission. Sandbox fills are classified sane/suspect (fill >5% from live
mid = suspect). **If sandbox fills prove dummy/static/unfilled, the sandbox
cannot validate the cost model as designed** — realized cost will then be
measured from live market depth (real prices), the sandbox serving as
order-shape plumbing only, and this log will say so explicitly rather than
stretching a meaningless comparison. The first checkpoint below carries that
verdict.

## Run status

- [x] Step 0 findings recorded (above)
- [x] Step 1 — credentials scaffold, token store w/ expiry + hot reload, .env convention
- [x] Step 1 — sandbox-guarded Upstox client + connectivity verification script
- [x] Step 2 — locked strategy ported (`backend/paper_trading/strategy.py`) with port-verification script
- [x] Step 2 — rebalance scheduler: signal → sandbox orders → fill polling → slippage logging
- [x] Step 3 — JSONL event log, status script, failure handling, kill switch
- [ ] Step 1 — human step: Soham generates sandbox token + market-data token
- [ ] Step 1 — connectivity verification passes end-to-end
- [ ] Live run started (scheduler running unattended)
- [ ] **Checkpoint 1 (~2-3 weeks in)** — infrastructure sanity check
- [ ] **Checkpoint 2 (~1-2 months in)** — first substantive cost comparison
- [ ] Ongoing updates at natural cadence
- [ ] **Concluding section** — when sample is statistically sufficient

## How to operate

```bash
python3.11 backend/paper_trading/scripts/paper_setup.py   # one-time scaffold + instructions
cp backend/paper_trading/.env.example backend/paper_trading/.env  # fill tokens
python3.11 backend/paper_trading/scripts/verify_connectivity.py   # Step 1.4 check
python3.11 backend/paper_trading/scripts/verify_port.py           # signal-port check
python3.11 backend/paper_trading/scheduler.py                     # run (add --dry-run first)
python3.11 backend/paper_trading/scripts/paper_status.py          # status anytime
python3.11 backend/paper_trading/scripts/paper_stop.py            # kill switch
```

See `backend/paper_trading/README.md` for details. All runtime state and the
append-only event log live under `states/paper_trading/` (gitignored).

---

<!-- Checkpoints are appended below as they occur. Nothing below is a final
verdict; this document is updated at natural checkpoints over an open-ended
run. -->

## Checkpoint 1 — TBD (~2-3 weeks in)

*Infrastructure sanity check — is the harness working correctly, are fills
logging as expected, any auth/connectivity issues found and fixed. NOT a
verdict on the cost model.*

- [ ] Scheduler uptime, boot count, clean restarts
- [ ] Fill behavior verdict: do sandbox orders complete? At meaningful prices?
- [ ] Auth/connectivity issues encountered and resolved

## Checkpoint 2 — TBD (~1-2 months in)

*First substantive comparison: realized cost-per-trade (mean AND distribution)
vs. backtest-assumed cost-per-trade. State whether the sample supports any
conclusion yet.*

- [ ] Realized slippage: mean/median/p10/p90 (bps and ₹/trade)
- [ ] Sandbox fill quality classification
- [ ] Sample-size reasoning (independent rebalances vs. bootstrap CI variance)

## Conclusion — TBD (when sample is sufficient)

*See task Step 5 for what must go here — the central realized-vs-assumed cost
comparison, and an honest verdict either way.*
