# TLA+ Specs

This folder contains lightweight formal specs for critical AlphaCore invariants.

## Files

- `OrderBook.tla`
  - Models bid/ask updates and mid-price maintenance.
  - Invariants:
    - `mid_price = (best_bid + best_ask) / 2`
    - no crossed book (`best_bid < best_ask`)

- `DetectionQueue.tla`
  - Models enqueue/process/ack lifecycle.
  - Invariants:
    - monotonic `seq_num`
    - processed IDs must have been enqueued first
    - no duplicate processing intent

- `KillSwitch.tla`
  - Models activation/deactivation of risk kill switch.
  - Invariant:
    - if kill switch is active, signal emission is not allowed

## Running with TLA+ Toolbox

1. Install TLA+ Toolbox from the official distribution.
2. Open this folder as a Toolbox spec workspace.
3. Create a model per module and check invariants.
4. Run TLC for bounded state-space exploration.

These specs are intentionally compact and map directly to engine-level invariants documented in `docs/invariants.md`.
