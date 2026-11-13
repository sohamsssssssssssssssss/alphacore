# Replication finding — 2026-11-13

Verdict **B: the supplied C++ components have the same class of unfenced
promotion hole**. This diagnoses repository components, not a deployed cluster.
No production C++ or model transition/invariant was changed.

## TLC trace

Full stdout/stderr: [SinglePrimaryPerEpoch.txt](tla_engine_models/traces/SinglePrimaryPerEpoch.txt).
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
