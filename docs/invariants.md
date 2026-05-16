# AlphaCore Engine Invariants

## Detection Engines

### Iceberg Detector
- Input assumptions:
  - Snapshot has valid bid/ask levels with non-negative volumes.
  - Time advances monotonically per symbol.
- Output guarantees:
  - Confidence score is bounded in `[0, 100]`.
  - Refill-based detections only fire after minimum refill count.
  - Active detections expire after stale horizon.

### Spoof Detector
- Input assumptions:
  - Consecutive snapshots are available for cancellation inference.
- Output guarantees:
  - `spoof_score` is bounded in `[0, 100]`.
  - Severity mapping is deterministic from score.
  - Alert list is capped per symbol.

### Flow Imbalance
- Input assumptions:
  - Bid/ask volumes are non-negative.
- Output guarantees:
  - Imbalance score is always in `[-1.0, 1.0]`.
  - Zero denominator returns neutral `0.0`.

## Signal Scoring

### Momentum
- Uses 1/5/15 lookback weighted bps returns.
- Missing history contributes `0.0` for that component.
- Identical prices yield `0.0` signal.

### Mean Reversion
- Uses rolling z-score over bounded window.
- Zero standard deviation yields `0.0`.

### OFI
- Defined as `(bid_vol - ask_vol) / (bid_vol + ask_vol)`.
- Always in `[-1, 1]`.

### Combined Signal
- Equal-weight average of normalized momentum/z-score/OFI.
- Clamped to `[-1, 1]`.
- Alpha score mapping is bounded to `[0, 100]`.

## Regulatory Controls

### Circuit Breaker
- Triggers iff one-cycle absolute move exceeds configured threshold.
- Halted symbol remains halted until reset.

### Kill Switch
- If active, signal generation is suppressed.
- Transition actions are idempotent for same target state.

### OTR (Order-to-Trade Ratio)
- Ratio is never negative.
- Breach status is deterministic from threshold comparison.

### Risk Limits
- Notional cap breach always rejects signal.
- Per-symbol rate cap breach always rejects signal.

## Backtest Metrics
- `final_equity >= 0` (capital clamped non-negative).
- `len(equity_curve) = total_trades + 1`.
- `max_drawdown` in `[0, 1]`.
- `win_rate` in `[0, 1]`.
- Sharpe returns finite float; zero for insufficient/zero-variance returns.

## Order Book Consistency
- Best bid is strictly less than best ask (`best_bid < best_ask`).
- Mid price equals `(best_bid + best_ask) / 2` within float tolerance.
- Spread in bps is positive whenever both sides exist.
