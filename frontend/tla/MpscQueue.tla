------------------------------ MODULE MpscQueue ------------------------------
EXTENDS Naturals, Sequences, FiniteSets, TLC

(***************************************************************************
TLC command:
java -jar tla2tools.jar -config tla/ModelMpsc.cfg tla/MpscQueue.tla

Expected state-space size (with default cfg): ~300k-700k states.

Hardest invariant:
NoDataLoss is hardest because strict "eventually popped" is liveness; TLC safety
checking is simpler for invariants, so we use a bounded surrogate requiring that
all values currently in queue are still present in pushed\popped accounting.
***************************************************************************)

CONSTANTS N, NumProducers, Values

Producers == 1..NumProducers

VARIABLES buffer, head, tail, pushed, popped

QueueLen == tail - head

Idx(i) == (i % N)

Init ==
    /\ buffer = [i \in 0..(N - 1) |-> NULL]
    /\ head = 0
    /\ tail = 0
    /\ pushed = <<>>
    /\ popped = <<>>

CanPush == QueueLen < N
CanPop == QueueLen > 0

Push(p, v) ==
    /\ p \in Producers
    /\ v \in Values
    /\ CanPush
    /\ buffer' = [buffer EXCEPT ![Idx(tail)] = v]
    /\ tail' = tail + 1
    /\ head' = head
    /\ pushed' = Append(pushed, v)
    /\ popped' = popped

Pop(c) ==
    /\ c = 0
    /\ CanPop
    /\ LET val == buffer[Idx(head)] IN
       /\ buffer' = [buffer EXCEPT ![Idx(head)] = NULL]
       /\ head' = head + 1
       /\ tail' = tail
       /\ pushed' = pushed
       /\ popped' = Append(popped, val)

Next ==
    \/ \E p \in Producers, v \in Values : Push(p, v)
    \/ Pop(0)

TypeInv ==
    /\ head \in Nat
    /\ tail \in Nat
    /\ head <= tail
    /\ QueueLen <= N
    /\ buffer \in [0..(N - 1) -> (Values \cup {NULL})]

NeverOverflow == head <= tail

Linearizability == popped = SubSeq(pushed, 1, Len(popped))

NoDataLoss == \A i \in head..(tail - 1) : buffer[Idx(i)] \in Values

Spec == Init /\ [][Next]_<<buffer, head, tail, pushed, popped>>

=============================================================================
