------------------------------ MODULE PrimaryBackup ------------------------------
(***************************************************************************
Fenced primary-backup replication for AlphaCore (2 nodes, ids 0 and 1).
This is the intended protocol that engine/src/heartbeat.* and
engine/src/replication.* implement. The unfenced model that TLC refuted
is kept in history/ together with its counterexample trace.

Each action changes only the acting node's own state; there is no atomic
remote demotion. The network may delay, reorder, drop and partition.

Protocol rules:
  a) Every node tracks maxSeen, the largest epoch carried by any message it
     has received (heartbeat or log entry; a promoted node's heartbeats are
     the epoch notifications).
  b) Promotion picks NextOwned(maxSeen, n): the smallest epoch > maxSeen
     owned by n (epoch % 2 = n). It sets epoch = maxSeen = that value, and
     both are persisted (Restart keeps them) before the node acts as primary.
     Owned epochs are the tie-break by node id: two distinct nodes can never
     hold the same epoch.
  c) Every heartbeat and log entry carries the sender's epoch.
  d) A receiver rejects a log entry with epoch < its maxSeen.
  e) A primary that receives epoch >= its own from the other node steps
     itself down. Under (b) equal epochs from a different node cannot occur;
     >= is kept so that an equal epoch still fences.
  A primary appends only while its lease is current (epoch = maxSeen).

NOT guaranteed (stated deliberately):
  - No quorum. Two nodes cannot prevent two primaries across a partition.
    Both may be primary at once in *different* epochs; this model allows it.
  - Fencing bounds the damage: once the partition heals, the older-epoch
    primary steps down and its writes are rejected by any node that has
    seen the newer epoch. Writes the stale primary committed locally during
    the partition are neither replicated nor reconciled; nothing here
    merges divergent histories.
  - Liveness is not checked.
  - Persistence: this model persists epoch/maxSeen across Restart. The C++
    implementation keeps them in memory only (no epoch metadata mechanism
    exists), so restart safety is not covered there. Owned epochs still keep
    a restarted node from colliding with its peer, but it may reuse one of
    its own earlier epochs.

TLC (tla2tools v1.7.4, ModelPrimaryBackup.cfg N=6 HeartbeatLoss=2 MaxMsgs=3,
-deadlock, 10 workers, 2026-11-13): no error; 526,142,487 states generated,
65,620,528 distinct, depth 44, 4 min 12 s. Mutation checks (same cfg):
NextOwned := maxSeen + 1 violates SinglePrimaryPerEpoch (2,577 distinct);
removing the rule (d) guard violates NoStaleApply (942 distinct).
***************************************************************************)
EXTENDS Naturals, FiniteSets, TLC

CONSTANTS
    N,             \* Bound on epoch numbers (0..N)
    HeartbeatLoss, \* Missed heartbeat ticks before a backup may promote
    MaxMsgs        \* Max messages in flight, and max entries per node

Nodes == {0, 1}
Other(n) == 1 - n
Max(a, b) == IF a >= b THEN a ELSE b
NextOwned(m, n) == IF (m + 1) % 2 = n THEN m + 1 ELSE m + 2

Msg == [type : {"hb", "entry"}, src : Nodes, dst : Nodes, epoch : 0..N, seq : 0..MaxMsgs]

VARIABLES
    role,       \* role[n] \in {"primary", "backup"}
    epoch,      \* epoch[n]: epoch n last promoted to (persisted)
    maxSeen,    \* maxSeen[n]: largest epoch n has seen (persisted)
    missed,     \* missed heartbeat ticks at a backup
    net,        \* set of in-flight messages
    link,       \* FALSE while the two nodes are partitioned
    nextSeq,    \* next log sequence number per node
    committed,  \* <<node, epoch, seq>> written to a primary's own log
    applied,    \* applied[n]: <<epoch, seq>> entries applied at n
    staleApply  \* ghost: staleApply[n] = TRUE once n applied an entry with epoch < its maxSeen

vars == <<role, epoch, maxSeen, missed, net, link, nextSeq, committed, applied, staleApply>>

\* Node 0 boots as primary via promote() from a fresh lease: NextOwned(0, 0) = 2.
Init ==
    /\ role = [n \in Nodes |-> IF n = 0 THEN "primary" ELSE "backup"]
    /\ epoch = [n \in Nodes |-> IF n = 0 THEN 2 ELSE 0]
    /\ maxSeen = [n \in Nodes |-> IF n = 0 THEN 2 ELSE 0]
    /\ missed = [n \in Nodes |-> 0]
    /\ net = {}
    /\ link = TRUE
    /\ nextSeq = [n \in Nodes |-> 0]
    /\ committed = {}
    /\ applied = [n \in Nodes |-> {}]
    /\ staleApply = [n \in Nodes |-> FALSE]

Send(m) ==
    /\ Cardinality(net) < MaxMsgs
    /\ net' = net \cup {m}

SendHeartbeat(n) ==
    /\ role[n] = "primary"
    /\ Send([type |-> "hb", src |-> n, dst |-> Other(n), epoch |-> epoch[n], seq |-> 0])
    /\ UNCHANGED <<role, epoch, maxSeen, missed, link, nextSeq, committed, applied, staleApply>>

Replicate(n) ==
    /\ role[n] = "primary"
    /\ epoch[n] = maxSeen[n]                 \* lease is current
    /\ nextSeq[n] < MaxMsgs
    /\ Send([type |-> "entry", src |-> n, dst |-> Other(n), epoch |-> epoch[n], seq |-> nextSeq[n]])
    /\ committed' = committed \cup {<<n, epoch[n], nextSeq[n]>>}
    /\ nextSeq' = [nextSeq EXCEPT ![n] = @ + 1]
    /\ UNCHANGED <<role, epoch, maxSeen, missed, link, applied, staleApply>>

Receive(m) ==
    /\ link
    /\ m \in net
    /\ LET d == m.dst
           fresh == m.epoch >= maxSeen[d]             \* rule (d)
           fence == role[d] = "primary" /\ m.epoch >= epoch[d]   \* rule (e)
       IN
       /\ net' = net \ {m}
       /\ maxSeen' = [maxSeen EXCEPT ![d] = Max(@, m.epoch)]      \* rule (a)
       /\ role' = IF fence THEN [role EXCEPT ![d] = "backup"] ELSE role
       /\ missed' = IF fence \/ (m.type = "hb" /\ fresh)
                        THEN [missed EXCEPT ![d] = 0] ELSE missed
       /\ applied' = IF m.type = "entry" /\ fresh
                         THEN [applied EXCEPT ![d] = @ \cup {<<m.epoch, m.seq>>}]
                         ELSE applied
       \* Ghost observes the effect on applied', not the guard above.
       /\ staleApply' = IF applied'[d] # applied[d] /\ m.epoch < maxSeen[d]
                            THEN [staleApply EXCEPT ![d] = TRUE] ELSE staleApply
       /\ UNCHANGED <<epoch, link, nextSeq, committed>>

MissHeartbeat(n) ==
    /\ role[n] = "backup"
    /\ missed[n] < HeartbeatLoss
    /\ missed' = [missed EXCEPT ![n] = @ + 1]
    /\ UNCHANGED <<role, epoch, maxSeen, net, link, nextSeq, committed, applied, staleApply>>

Promote(n) ==                                          \* rule (b)
    /\ role[n] = "backup"
    /\ missed[n] >= HeartbeatLoss
    /\ NextOwned(maxSeen[n], n) <= N
    /\ epoch' = [epoch EXCEPT ![n] = NextOwned(maxSeen[n], n)]
    /\ maxSeen' = [maxSeen EXCEPT ![n] = NextOwned(maxSeen[n], n)]
    /\ role' = [role EXCEPT ![n] = "primary"]
    /\ missed' = [missed EXCEPT ![n] = 0]
    /\ UNCHANGED <<net, link, nextSeq, committed, applied, staleApply>>

\* Crash and restart as backup; persisted epoch/maxSeen survive.
Restart(n) ==
    /\ role' = [role EXCEPT ![n] = "backup"]
    /\ missed' = [missed EXCEPT ![n] = 0]
    /\ UNCHANGED <<epoch, maxSeen, net, link, nextSeq, committed, applied, staleApply>>

Partition == link /\ link' = FALSE
             /\ UNCHANGED <<role, epoch, maxSeen, missed, net, nextSeq, committed, applied, staleApply>>
Heal == ~link /\ link' = TRUE
        /\ UNCHANGED <<role, epoch, maxSeen, missed, net, nextSeq, committed, applied, staleApply>>
Drop(m) == m \in net /\ net' = net \ {m}
           /\ UNCHANGED <<role, epoch, maxSeen, missed, link, nextSeq, committed, applied, staleApply>>

Next ==
    \/ \E n \in Nodes : SendHeartbeat(n) \/ Replicate(n) \/ MissHeartbeat(n)
                        \/ Promote(n) \/ Restart(n)
    \/ \E m \in net : Receive(m) \/ Drop(m)
    \/ Partition \/ Heal

Spec == Init /\ [][Next]_vars

\* ─── Invariants ─────────────────────────────────────────────────────

TypeInv ==
    /\ role \in [Nodes -> {"primary", "backup"}]
    /\ epoch \in [Nodes -> 0..N]
    /\ maxSeen \in [Nodes -> 0..N]
    /\ missed \in [Nodes -> 0..HeartbeatLoss]
    /\ net \subseteq Msg /\ Cardinality(net) <= MaxMsgs
    /\ link \in BOOLEAN
    /\ nextSeq \in [Nodes -> 0..MaxMsgs]
    /\ \A n \in Nodes : epoch[n] <= maxSeen[n]

\* At most one primary per epoch, even while both nodes are primary.
SinglePrimaryPerEpoch ==
    ~(role[0] = "primary" /\ role[1] = "primary" /\ epoch[0] = epoch[1])

\* No entry from an older epoch is applied after a newer epoch was seen.
NoStaleApply ==
    \A n \in Nodes : ~staleApply[n]

\* An (epoch, seq) slot is written by at most one node, and every applied
\* entry is one that its sender actually committed.
CommittedDataSafe ==
    /\ \A c1, c2 \in committed : (c1[2] = c2[2] /\ c1[3] = c2[3]) => c1[1] = c2[1]
    /\ \A n \in Nodes : \A a \in applied[n] : <<Other(n), a[1], a[2]>> \in committed

=============================================================================
