# Replication finding — 2026-11-13

Verdict **B: the supplied C++ components have the same class of unfenced
promotion hole**. This diagnoses repository components, not a deployed cluster.
No production C++ or model transition/invariant was changed.

## TLC trace

Full stdout/stderr: [SinglePrimaryPerEpoch.txt](tla_engine_models/history/SinglePrimaryPerEpoch.txt)
(moved to `history/` with the unfenced model at resolution; content unchanged).
TLC exits 12 with ModelPrimaryBackup.cfg:

1. Primary is at epoch 1; backup is at epoch 0; primary remains alive.
2. BackupMissHeartbeat increments the backup's missed-heartbeat count to 1.
3. BackupMissHeartbeat increments it to 2.
4. BackupPromote sets backupRole to primary and backupEpoch to backupEpoch+1,
   which is 1. The original primary remains at epoch 1: two primaries in one epoch.

The failing action never fences/demotes the original primary and derives its
new epoch only from stale local knowledge. The passing specs/tla model has
BootBackup copy n1_epoch, BootPrimary guard `n2_state # "PRIMARY"`, and,
critically, BackupPromote performs `n1_state' = "UNKNOWN"` atomically while
updating active_primary_epoch. ReceiveEpochNotify also demotes a primary
when it receives a higher epoch, and BackupApplyLog checks message epochs.
The atomic remote demotion is a modeling assumption, not evidence of an
implemented distributed fencing protocol.

## C++ mapping (line numbers at this commit)

- heartbeat.cpp:21: `LeaderLease::LeaderLease() : epoch_(1) {}`. Thus a pristine
  C++ backup promotes 1 -> 2, unlike the model's 0 -> 1. The literal initial
  numeric trace is different; the unsafe stale-local-epoch promotion remains.
- heartbeat.cpp:27–28: `return epoch_.fetch_add(1, std::memory_order_acq_rel) + 1;`
  changes only the local lease.
- heartbeat.cpp:31–32: `return backup_epoch > epoch();`. An equal-epoch collision
  would not request step-down, and no production caller of should_step_down exists.
- heartbeat.cpp:158–162: the primary loop only calls `(void)send_heartbeat();`
  while running_primary_ is true. It does not receive epoch notifications or fence itself.
- heartbeat.cpp:203–205: a received heartbeat updates last_primary_epoch and
  resets misses; it does not advance the local lease.
- heartbeat.cpp:209–214: after three misses, `if (lease_.epoch() >= last_primary_epoch)`
  calls `lease_.promote()`, sets promoted_, and invokes the callback. It does
  not coordinate with or revoke the old primary.
- replication.cpp:124–135: `ReplicationLog::append` writes the entry to its local
  journal without a lease/epoch check.
- replication.cpp:271–276: the receiver decodes a length, reads payload bytes,
  then calls `apply_entry(entry)`; there is no replicated epoch validation.

The existing HA chaos test's promotion callback manually increments the lease
and calls the step-down predicate; this test-only callback is not a production
fencing path (engine/tests/chaos/ha_chaos_test.cpp:355–365).

## Executable regression (expected failure)

A prior primary promotion leaves its lease at 2, while a stale/restarted backup
starts at 1. The live primary sends heartbeats into a UDP packet sink to model
a partition. The backup receives none, times out, and promotes to 2 while the
original primary is still running. Both now advertise the same epoch. This
uses the actual monitor/lease implementation, not mocks. It exits **1**, with:

```
live primary epoch=2; promoted backup epoch=2; same-epoch collision=YES
FAIL: SinglePrimaryPerEpoch
```

Build/run explicitly:

```
cmake --build .reproduce/engine-release --target split_brain_counterexample
.reproduce/engine-release/split_brain_counterexample
```

The target is EXCLUDE_FROM_ALL and registered with CTest under the label
known-counterexample; existing CI runs explicit passing executables and
excludes this regression. It is not marked WILL_FAIL and its assertion is
not inverted. The TLC failure runs as the separate advisory
`tla-known-counterexample` job with continue-on-error, keeping the failure
visible while the main TLA job checks the passing models.

A production fix would need an actual fencing/lease authority and restart-safe
epoch handling. That design and C++ logic changes are deliberately outside T1.

## Resolution 2026-11-13

Fixed in `e1c8bd1` (T1, spec) and `3b8f038` (T2, C++). The text above is the
original diagnosis; its line numbers refer to the pre-fix commit.

### Protocol (specs/tla_engine_models/PrimaryBackup.tla)

Each action changes only the acting node; there is no atomic remote demotion.

- (a) Every node tracks `max_seen`, the largest epoch on any heartbeat or log
  entry it received. A promoted node's heartbeats are its epoch notifications.
- (b) Promotion takes the smallest epoch greater than `max_seen` that the node
  *owns* (epoch % 2 == node id). In the model, epoch and `max_seen` survive
  restart.
- (c) Heartbeats and log entries carry the sender's epoch.
- (d) A receiver rejects an entry whose epoch is below its `max_seen`.
- (e) A primary that sees an epoch >= its own from the other node steps down.
- **Tie-break: by node id, through epoch ownership.** Two distinct nodes can
  never hold the same epoch. `>=` is kept so that an equal epoch still fences.
- **Deviation from the brief.** The brief specified `max_seen + 1`. That cannot
  satisfy SinglePrimaryPerEpoch for two nodes without a quorum: a partitioned
  node that never saw the peer's epoch picks the same number. TLC confirms
  this: with `NextOwned := maxSeen + 1` and the same config,
  SinglePrimaryPerEpoch is violated after 2,577 distinct states. Removing the
  rule (d) guard violates NoStaleApply after 942 distinct states. These
  mutation runs show both invariants can fail.

### TLC, same constants as the failing config (N=6, HeartbeatLoss=2, MaxMsgs=3), tla2tools v1.7.4

| Model | Result | States generated | Distinct states |
|---|---|---:|---:|
| Before: unfenced (`history/PrimaryBackup.tla`) | SinglePrimaryPerEpoch violated at depth 4 | 71 | 47 |
| After: fenced (`PrimaryBackup.tla`) | no error, depth 44, 4 min 12 s on 10 workers | 526,142,487 | 65,620,528 |

The after-model checks TypeInv, SinglePrimaryPerEpoch, NoStaleApply and
CommittedDataSafe. It also models partition/heal, message loss and reordering,
and restart. CI runs it in the main `tla` job. The `tla-known-counterexample`
advisory job is removed.

### C++

- **`heartbeat.*`**
  - `LeaderLease(node_id)` tracks `epoch`, `max_seen` and role.
  - `promote()` follows (b).
  - `accept(e)` applies (a), (d) and (e), and is the production caller of
    `should_step_down` (now `>=`).
  - The primary loop reads epoch notifications and stops on step-down.
  - A promoted backup notifies the last-seen peer address, and steps down if
    it sees an epoch >= its own.
  - The heartbeat packet is v1: 16 B, `[u32 version][u32 node_id][u64 epoch]`.
- **`replication.*`**
  - `append()` refuses unless the lease is current.
  - The frame is v1: `[u32 len][u16 version][u64 epoch][payload]`. A receiver
    drops the connection on an unknown version or an oversized length, and
    rejects stale epochs before `apply_entry`.
  - The on-disk journal format is unchanged.
  - `BackupReceiver` fd teardown is now race-free under TSan.
- **Regression.** `split_brain_counterexample` changed only to give the two
  nodes distinct ids; its assertion and exit codes are unchanged.
  - Before: `live primary epoch=2; promoted backup epoch=2; same-epoch collision=YES`, exit 1.
  - After: `live primary epoch=2; promoted backup epoch=1; same-epoch collision=no`, exit 0.
  - It now runs in CI.
- **New `fencing_test`** (Release and TSan):
  - a stale entry is rejected after promotion;
  - the old primary steps down on heal and its appends are refused;
  - equal-epoch tie;
  - restart with a stale epoch.
- **`ha_chaos_test` test 3** uses the production promote and step-down path
  instead of the test-only fencing callback.

### Still NOT guaranteed

- **No quorum.** During a partition both nodes can be primary, in different
  epochs. The model allows this and the C++ tests demonstrate it. Writes
  committed by the stale primary during the partition are neither replicated
  nor reconciled. Fencing only rejects them once the receiver has seen the
  newer epoch, and makes the stale primary step down after heal.
- **Restart safety is not covered in C++.** No epoch metadata mechanism
  existed, so the epoch is kept in memory. Owned epochs still keep a restarted
  node from colliding with its peer, but it can reuse one of its own earlier
  epochs. The TLA model persists the epoch, so it does not cover this case.
- **Only the 2-node case.** `LeaderLease` rejects node ids other than 0 and 1.
- **No liveness checking.** The TLC results are bounded checks, not proofs of
  the unbounded system.
