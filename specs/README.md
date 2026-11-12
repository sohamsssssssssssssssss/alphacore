# TLA+ model sets

`specs/tla/` contains the bounded queue and replication models used by the
original engine CI. `specs/tla_engine_models/` contains the separately authored
models formerly stored under frontend/tla; they have different variables,
transition rules, invariants and bounds, so they are retained as a separate
set rather than presented as duplicate proofs. CI checks both models in
`tla/` and the existing bounded configurations listed below from
`tla_engine_models/`; it does not check every alternative configuration.

## Timed checks — 2026-11-13

TLC 1.7.4 release (TLC reports 2.19), Java 25.0.2, macOS arm64, 2 GiB heap.
No model, invariant or configuration was modified for these measurements.
Each execution had a 300-second timeout.

| Model | Existing configuration | Seconds | Result |
|---|---|---:|---|
| MpscQueue | ModelMpsc_tiny.cfg | 0.89 | pass |
| MatchingEngine | ModelMatching_small2.cfg | 1.04 | pass |
| OrderBook | ModelOrderBook_small3.cfg | 0.94 | pass |
| PrimaryBackup | ModelPrimaryBackup.cfg | 0.89 | invariant failure, exit 12 |

All four completed under five minutes, so CI runs all four with a per-model
300-second timeout. These small configurations are bounded checks, not proofs
of larger configurations or the implementation. Other supplied configurations
remain available locally and were not timed in this pass.

### Known counterexample (kept visible in CI)

PrimaryBackup violates `SinglePrimaryPerEpoch`: the initial primary is alive
at epoch 1; the backup misses two heartbeats and promotes from backupEpoch=0
to backupEpoch=1 while the original primary remains alive at epoch 1. The
unchanged model therefore has two primaries in the same epoch. The four-state
counterexample is reproducible with:

```sh
java -cp .reproduce/tla/tla2tools.jar tlc2.TLC \
  specs/tla_engine_models/PrimaryBackup.tla \
  -config specs/tla_engine_models/ModelPrimaryBackup.cfg -deadlock
```

This failure is not skipped, made non-fatal, or addressed by removing an
invariant. Fixing spec logic is outside this phase's authorization.
