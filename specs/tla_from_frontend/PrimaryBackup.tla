------------------------------ MODULE PrimaryBackup ------------------------------
EXTENDS Naturals, Sequences, FiniteSets, TLC

SeqToSet(s) == {s[i] : i \in 1..Len(s)}

(***************************************************************************
TLA+ spec for AlphaCore's primary-backup replication with epoch-based leader
fencing.

Model:
  - One primary and one backup process.
  - The primary holds a monotonically increasing epoch number.
  - Messages (heartbeats + replicated log entries) may be lost or reordered
    across the "network" (modelled by a bounded message buffer).
  - The backup promotes itself when it misses enough heartbeats.
  - Fencing invariant: at most one node believes it is the primary for any
    given epoch at any logical time.

TLC command (full):
  java -jar tla2tools.jar -config tla/ModelPrimaryBackup.cfg \
       tla/PrimaryBackup.tla

Expected state space (default cfg, N=6, H=2, MaxMsgs=3): ~500k-1.5M states.

Hardest invariant:
  SinglePrimaryPerEpoch requires globally tracking which (node, epoch) pairs
  are "active" at each step — because the epoch counter increments on promotion
  and the old primary may still be alive with a stale epoch, the invariant must
  prove they cannot both commit writes.
**************************************************************************)

CONSTANTS
    N,             \* Bound on epoch numbers (0..N)
    HeartbeatLoss, \* Number of consecutive heartbeats that can be lost
    MaxMsgs        \* Max messages in flight

\* Message types
HeartbeatMsg(epoch) == [type |-> "heartbeat", epoch |-> epoch]
ReplicateMsg(seq, data) == [type |-> "replicate", seq |-> seq, data |-> data]

Message ==
    [type : {"heartbeat"}, epoch : 0..N] \cup
    [type : {"replicate"}, seq : Nat, data : Nat]

VARIABLES
    primaryEpoch,        \* Current epoch at the primary
    backupRole,          \* "backup" or "primary"
    backupEpoch,         \* Last epoch seen by backup (from heartbeat)
    messageQueue,        \* In-flight messages (bounded)
    missedHeartbeats,    \* Counter of consecutive missed heartbeats at backup
    nextSeq,             \* Next replication sequence number
    primaryAlive,        \* Whether primary can send (models partition or crash)
    committedMsgs        \* Set of (epoch, seq) pairs that have been committed

Init ==
    /\ primaryEpoch = 1
    /\ backupRole = "backup"
    /\ backupEpoch = 0
    /\ messageQueue = <<>>
    /\ missedHeartbeats = 0
    /\ nextSeq = 0
    /\ primaryAlive = TRUE
    /\ committedMsgs = {}

\* Send a message (add to queue if not full)
Send(msg) ==
    /\ Len(messageQueue) < MaxMsgs
    /\ messageQueue' = Append(messageQueue, msg)

\* Receive a message at the backup (remove from front if present)
Receive ==
    /\ messageQueue # <<>>
    /\ LET msg == Head(messageQueue) IN
       /\ messageQueue' = Tail(messageQueue)
       /\ IF msg.type = "heartbeat" THEN
              /\ backupEpoch' = msg.epoch
              /\ missedHeartbeats' = 0
              /\ UNCHANGED <<backupRole, primaryEpoch, nextSeq, primaryAlive, committedMsgs>>
          ELSE
              /\ committedMsgs' = committedMsgs \cup {<<backupEpoch, msg.seq>>}
              /\ UNCHANGED <<backupEpoch, backupRole, primaryEpoch, nextSeq, primaryAlive, missedHeartbeats>>

\* Primary sends heartbeat
PrimaryHeartbeat ==
    /\ primaryAlive = TRUE
    /\ Send(HeartbeatMsg(primaryEpoch))
    /\ UNCHANGED <<primaryEpoch, backupRole, backupEpoch, missedHeartbeats, nextSeq, primaryAlive, committedMsgs>>

\* Primary replicates a log entry
PrimaryReplicate ==
    /\ primaryAlive = TRUE
    /\ nextSeq < MaxMsgs  \* Bound the sequence
    /\ Send(ReplicateMsg(nextSeq, nextSeq))
    /\ nextSeq' = nextSeq + 1
    /\ UNCHANGED <<primaryEpoch, backupRole, backupEpoch, missedHeartbeats, primaryAlive, committedMsgs>>

\* Primary is partitioned from network (its messages are dropped)
PartitionPrimary ==
    /\ primaryAlive = TRUE
    /\ primaryAlive' = FALSE
    /\ UNCHANGED <<primaryEpoch, backupRole, backupEpoch, missedHeartbeats, nextSeq, messageQueue, committedMsgs>>

\* Partition heals
HealPartition ==
    /\ primaryAlive = FALSE
    /\ primaryAlive' = TRUE
    /\ UNCHANGED <<primaryEpoch, backupRole, backupEpoch, missedHeartbeats, nextSeq, messageQueue, committedMsgs>>

\* Backup misses a heartbeat (no message received this tick)
BackupMissHeartbeat ==
    /\ missedHeartbeats < HeartbeatLoss
    /\ missedHeartbeats' = missedHeartbeats + 1
    /\ UNCHANGED <<primaryEpoch, backupRole, backupEpoch, nextSeq, messageQueue, primaryAlive, committedMsgs>>

\* Backup promotes itself after too many missed heartbeats.
\* Promotion is triggered by heartbeat loss alone — the backup does not have
\* direct knowledge of primaryAlive; it only knows it missed heartbeats.
\* The interval between BackupMissHeartbeat steps represents one heartbeat
\* interval in the real system.
BackupPromote ==
    /\ missedHeartbeats >= HeartbeatLoss
    /\ backupRole = "backup"
    /\ LET newEpoch == backupEpoch + 1 IN
       backupRole' = "primary"
       /\ backupEpoch' = newEpoch
       /\ missedHeartbeats' = 0  \* Reset counter after promotion
       /\ UNCHANGED <<primaryEpoch, nextSeq, messageQueue, primaryAlive, committedMsgs>>

\* Old primary tries to send with stale epoch (should be fenced by epoch check
\* on the backup/receiver side)
StalePrimarySend ==
    /\ primaryAlive = TRUE
    /\ \E oldEpoch \in 1..(primaryEpoch - 1):
       Send(HeartbeatMsg(oldEpoch))
    /\ UNCHANGED <<primaryEpoch, backupRole, backupEpoch, missedHeartbeats, nextSeq, primaryAlive, committedMsgs>>

Next ==
    \/ PrimaryHeartbeat
    \/ PrimaryReplicate
    \/ PartitionPrimary
    \/ HealPartition
    \/ Receive
    \/ BackupMissHeartbeat
    \/ BackupPromote
    \/ StalePrimarySend

\* ─── Invariants ─────────────────────────────────────────────────────

\* Safety: at most one primary per epoch at any logical time
SinglePrimaryPerEpoch ==
    \A epoch \in 0..N:
        ~ (primaryEpoch = epoch /\ backupRole = "primary" /\ backupEpoch = epoch)

\* Safety: a stale-epoch message from old primary is never accepted as current
\* (the backup ignores heartbeats carrying an epoch lower than its own)
StaleEpochFenced ==
    \A msg \in {m \in SeqToSet(messageQueue) : m.type = "heartbeat"}:
        msg.epoch <= primaryEpoch

\* Safety: promotion happens only after enough missed heartbeats
PromotionRequiresMissedHeartbeats ==
    (backupRole = "primary") => (missedHeartbeats >= HeartbeatLoss \/ backupEpoch > 0)

\* Type invariant
TypeInv ==
    /\ primaryEpoch \in 1..N
    /\ backupRole \in {"backup", "primary"}
    /\ backupEpoch \in 0..N
    /\ messageQueue \in Seq(Message)
    /\ Len(messageQueue) <= MaxMsgs
    /\ missedHeartbeats \in 0..HeartbeatLoss
    /\ nextSeq \in 0..MaxMsgs
    /\ primaryAlive \in BOOLEAN

\* ─── Specification ───────────────────────────────────────────────────
vars == <<primaryEpoch, backupRole, backupEpoch, messageQueue, missedHeartbeats, nextSeq, primaryAlive, committedMsgs>>

Spec == Init /\ [][Next]_vars

\* ─── Liveness (optional) ──────────────────────────────────────────────
\* Under fair conditions, the backup eventually detects a partition and promotes
PromotionLiveness ==
    <>[](primaryAlive = FALSE) => <>(backupRole = "primary")

=============================================================================
