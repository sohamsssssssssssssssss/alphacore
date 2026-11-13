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
| PrimaryBackup (unfenced, now `history/`) | ModelPrimaryBackup.cfg | 0.89 | invariant failure, exit 12 |

These small configurations are bounded checks, not proofs of larger
configurations or the implementation. Other supplied configurations remain
available locally and were not timed in this pass.

### Replication: counterexample found, then fixed

The original PrimaryBackup model violated `SinglePrimaryPerEpoch`: the initial
primary is alive at epoch 1; the backup misses two heartbeats and promotes from
backupEpoch=0 to backupEpoch=1 while the original primary remains alive at
epoch 1. That model, its config and the four-state trace are kept unchanged in
`tla_engine_models/history/` as the record; they are not run in CI:

```sh
cd specs/tla_engine_models/history
java -cp ../../../.reproduce/tla/tla2tools.jar tlc2.TLC PrimaryBackup.tla \
  -config ModelPrimaryBackup.cfg -deadlock
```

`tla_engine_models/PrimaryBackup.tla` now specifies the fenced protocol and
passes with the same constants (N=6, HeartbeatLoss=2, MaxMsgs=3): 526,142,487
states generated, 65,620,528 distinct, 4 min 12 s on 10 workers (macOS arm64,
8 GiB heap, 2026-11-13). It is too large for the 300-second per-model budget
above, so CI runs it as a separate step with a 2400-second timeout. See
[REPLICATION_FINDING.md](REPLICATION_FINDING.md).
