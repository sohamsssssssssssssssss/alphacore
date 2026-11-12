# AlphaCore — Upstox Sandbox Paper-Trading Harness (top-quartile basket, k=12, monthly RS)

Validates whether **execution-level realities change the cost picture** for the
Phase 1/2 winner — **top-quartile basket (k=12 of 49), monthly rebalance,
21-day lookback**, Sharpe **0.6610** (95% CI [0.5718, 1.9514]) on the
49-symbol NSE universe — versus the backtest's assumed transaction costs.
(Re-pointed from the original K=1 config, Sharpe -1.57, which was
cost-dominated; see `hypothesis.md` for both pre-committed hypotheses.)

> **This package is isolated from the live AlphaCore trading path.** It only
> ever talks to the Upstox **sandbox** API (`https://api-sandbox.upstox.com`)
> with a dedicated **sandbox access token** — never live credentials or
> endpoints. It never imports or drives `backend/execution/`,
> `backend/paper_runner.py`, or the live broker code.

## Pre-committed hypothesis (do not skip)

`hypothesis.py` is printed by the harness and the report **before any sandbox
data is pulled**: sandbox-observed execution costs are **expected to be higher
than backtest-assumed costs** (the original K=1 validation hypothesis). The
Phase 1/2 basket hypotheses (`hypothesis.md`) were satisfied; this harness
validates execution-level costs for the winning basket config.

## 1. Get a sandbox token (5 minutes, one-time per 30 days)

1. Log in at the [Upstox developer console](https://account.upstox.com/developer/apps).
2. In the **Sandbox** section click **New Sandbox App** (one sandbox app per
   user). The redirect/postback URL fields are placeholders — fill anything.
3. In your sandbox app, click **Generate** → copy the **sandbox access token**
   (valid **30 days**, sandbox-only — cannot touch live trading).
4. Export it:
   ```bash
   export UPSTOX_SANDBOX_TOKEN=your_sandbox_token_here
   ```

## 2. Environment (Python 3.11 — required)

```bash
cd backend
python3.11 -m venv sandbox/.venv
sandbox/.venv/bin/pip install -r sandbox/requirements.txt
```

(Do **not** use the system-default python; the harness is pinned to python3.11
per the research environment.)

## 3. Dry run (no API calls — validates the whole pipeline)

```bash
cd backend
sandbox/.venv/bin/python3.11 -m sandbox.harness --dry-run --rebalance-date 2026-08-31
```

Prints: pre-committed hypothesis → per-symbol data fetch status → the full
49-symbol cross-sectional ranking → the **top-quartile basket (k=12)** target
legs (side, qty, ref price, backtest-assumed cost in INR and bps) → the exact
order payloads that *would* be sent, with **real Upstox instrument keys
(`NSE_EQ|<ISIN>`) resolved from Upstox's published instrument master**
(downloaded once and cached in `instruments_cache.json`; no sandbox API calls
are made).

Without `--rebalance-date`, the harness uses `--auto`: the **most recent
scheduled month-end (last trading day of month) on/before today** from the
fetched trading calendar. Run on/after the month-end this is the current
month's last trading day; run mid-month it resolves to the previous month's
month-end (the current one hasn't happened yet). The resolved date is always
printed as `[SCHEDULE] Rebalance date: ...` for verification.

## 4. Live sandbox execution

```bash
cd backend
export UPSTOX_SANDBOX_TOKEN=...
sandbox/.venv/bin/python3.11 -m sandbox.harness --rebalance-date 2026-08-31
```

Per order leg it:
* logs the **verbatim** HTTP request and response (headers redacted, body in
  full) to the terminal **and** `sandbox/logs/raw_api_*.txt`
* best-effort polls order-history / order-trades (see limitation below) and
  logs those raw responses too
* records a JSONL event in `sandbox/logs/rebalance_<date>.jsonl` with
  `fill_status` = `CONFIRMED` (API returned a fill price), `REJECTED`
  (API returned an error), `ACCEPTED` (order accepted, no fill data), or
  `UNCONFIRMED` (nothing observable) — **fills are never synthesized**.

Options: `--budget INR` (default ₹10,00,000 split across targets), `--k N`
(basket size; default top-quartile auto, 12 of 49 — same as the Phase 1
backtest), `--order-type MARKET|LIMIT` (+`--limit-price`), `--is-amo`,
`--place-rotation-sells` (SELL legs for names leaving the previous basket).

## 5. Cost comparison report

```bash
cd backend
sandbox/.venv/bin/python3.11 -m sandbox.compare_costs
```

Reads all `sandbox/logs/rebalance_*.jsonl` and prints/writes
`logs/cost_comparison_report.md`: backtest-assumed costs (repo CostModel
defaults: `k_impact=0.0015`, ₹20 brokerage/trade, STT 0.1% sell-side, 10 bps
assumed half-spread) vs sandbox-observed slippage/fees per leg, plus the
verdict against the pre-committed hypothesis.

## Backtest: top-quartile basket + rebalance frequency (Phase 1, Step 1)

`basket_backtest.py` runs the K=1 signal's **config-level extension** — the
same untouched `rs_signal.py` 21-day lookback and cross-sectional ranking, but
selecting a **top-quartile basket (k = n//4, 12 of 49)** at **monthly** or
**quarterly** cadence. It reuses the repo's canonical metric functions
(`engines/backtest_metrics.compute_sharpe`, `stationary_bootstrap_sharpe_ci`)
and the repo `CostModel` defaults + 10 bps assumed half-spread.

```bash
cd backend
sandbox/.venv/bin/python3.11 -m sandbox.basket_backtest --frequency monthly
sandbox/.venv/bin/python3.11 -m sandbox.basket_backtest --frequency quarterly
```

Prints the pre-committed hypothesis (`hypothesis.md`) before any data is
pulled, then the per-rebalance table and a `[JSON]` summary line (Sharpe, 95%
CI, win-alignment as beats-market rate, avg legs/turnover per rebalance).

Conventions locked for comparability with the 9-config table (also stated in
`hypothesis.md`): per-rebalance-period returns annualized ×√12 (monthly) or
×√4 (quarterly); equal-weight at entry with **delta-only** trading (no top-up
rebalancing); fills at the next session's open after each rebalance close.
Caveats: symbols that fail to fetch (e.g. TATAMOTORS via yfinance) are
dropped from the ranking; the bootstrap CI is centered on its own
(risk-free-unadjusted) point estimate, so it is not centered on the
`compute_sharpe` headline value.

### Phase 2: overfit sanity check flags

`rs_signal.py` lookback is now parameterized (default `LOOKBACK_TRADING_DAYS`
= 21, backward-compatible — existing callers unchanged), and `basket_backtest.py`
accepts `--k`, `--lookback`, `--start`, and `--cache`:

```bash
# split-sample halves (same logic, sub-windows by calendar date)
sandbox/.venv/bin/python3.11 -m sandbox.basket_backtest --cache /tmp/p2_full.pkl \
    --as-of 2023-08-13 --start 2020-08-14   # H1: 2020-08 -> 2023-08
sandbox/.venv/bin/python3.11 -m sandbox.basket_backtest --cache /tmp/p2_full.pkl \
    --as-of 2026-08-13 --start 2023-08-14   # H2: 2023-08 -> 2026-08

# parameter sensitivity (monthly, full window)
sandbox/.venv/bin/python3.11 -m sandbox.basket_backtest --cache /tmp/p2_full.pkl --k 10
sandbox/.venv/bin/python3.11 -m sandbox.basket_backtest --cache /tmp/p2_full.pkl --k 15
sandbox/.venv/bin/python3.11 -m sandbox.basket_backtest --cache /tmp/p2_full.pkl --lookback 18
sandbox/.venv/bin/python3.11 -m sandbox.basket_backtest --cache /tmp/p2_full.pkl --lookback 25
```

`--cache PATH` loads a saved closes/adv/opens pickle if present (clipped to
`--as-of`), otherwise fetches fresh and saves it — all Phase 2 runs used one
cached dataset so every config sees byte-identical prices. Note: yfinance
fetches are flaky under rate limiting (missing bars silently degrade results —
observed Sharpe swing 0.66 -> 0.35 on one degraded fetch); re-fetch until the
per-symbol bar counts look uniform, then lock the cache.

## Sandbox limitations you should know (verified against Upstox docs/SDK)

## Sandbox limitations you should know (verified against Upstox docs/SDK)

| Item | Status in sandbox |
|---|---|
| Order placement (`/v2/order/place`, `/v3/...`) | ✅ enabled |
| Modify / Cancel orders | ✅ enabled |
| Order history / order trades (fills) | ❌ **not sandbox-enabled yet** — the harness polls anyway and logs the raw API response; if no fill data comes back, the leg is recorded `UNCONFIRMED`, never approximated |
| Market quotes / master contract | ❌ the sandbox API does not expose quotes/master — prices come from yfinance daily bars (same source as the backtest); instrument keys are resolved from Upstox's **published instrument master** (`assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz`, `instruments.py`), cached in `instruments_cache.json`. Unresolvable symbols **fail loudly** — there is no numeric-token fallback (the old `NSE_EQ\|<numeric>` guesses were rejected by the order API with `UDAPI100011 Invalid Instrument key`) |
| Fees/brokerage | ❌ not charged in sandbox — observed fees will be whatever the API reports (typically none) |
| Token validity | 30 days per sandbox app; regenerate from the console |

Sandbox fills are **emulated**, not live exchange fills: slippage observed here
is Upstox's emulation, not market microstructure. That is precisely why the
report compares it against assumed costs rather than claiming live fidelity.

## Files

```
backend/sandbox/
├── hypothesis.py        # pre-committed hypothesis (printed before every run)
├── hypothesis.md        # pre-committed hypotheses: Phase 1 Step 1 basket + Phase 2 overfit sanity check
├── universe.py          # 49-symbol universe (Nifty 50 minus SBILIFE) + historical token snapshot (reference only)
├── instruments.py       # Upstox instrument master download/cache + symbol -> instrument_key lookup (fail-loud)
├── prices.py            # yfinance daily bars, ADV (+open prices for backtests)
├── rs_signal.py         # cross-sectional relative strength, parameterized lookback (default 21; Phase 2)
├── basket_backtest.py   # top-quartile basket backtest, monthly/quarterly (Phase 1) + --k/--lookback/--start/--cache (Phase 2)
├── costs.py             # backtest-assumed cost mirror + observed-fill parsing
├── upstox_sandbox.py    # raw sandbox API client + verbatim request/response log
├── harness.py           # CLI: signal -> top-quartile basket plan -> sandbox execution -> logs
├── compare_costs.py     # backtest-assumed vs sandbox-observed report
├── tests/               # pytest suite (run: sandbox/.venv/bin/pytest sandbox/tests)
└── logs/                # raw_api_*.txt + rebalance_*.jsonl + reports (gitignored)
```
