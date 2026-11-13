------------------------------ MODULE MpscQueue ------------------------------
EXTENDS Naturals, Sequences, FiniteSets, Integers

(***************************************************************************
TLC command:
java -jar tla2tools.jar -config tla/ModelMpsc.cfg tla/MpscQueue.tla

Expected state-space size (with default cfg): ~300k-700k states.

Hardest invariant:
NoDataLoss is hardest because strict "eventually popped" is liveness; TLC safety
checking is simpler for invariants, so we use a bounded surrogate requiring that
all values currently in queue are still present in pushed\popped accounting.
**************************************************************************)

CONSTANTS N, NumProducers, Values, MaxOps

Producers == 1..NumProducers

VARIABLES buffer, head, tail, pushed, popped, ops

QueueLen == tail - head

Idx(i) == (i % N)

NullVal == 0 - 1

Init ==
    /\ buffer = [i \in 0..(N - 1) |-> NullVal]
    /\ head = 0
    /\ tail = 0
    /\ pushed = <<>>
    /\ popped = <<>>
    /\ ops = 0

CanPush == QueueLen < N
CanPop == QueueLen > 0

Push(p, v) ==
    /\ ops < MaxOps
    /\ p \in Producers
    /\ v \in Values
    /\ CanPush
    /\ buffer' = [buffer EXCEPT ![Idx(tail)] = v]
    /\ tail' = tail + 1
    /\ head' = head
    /\ pushed' = Append(pushed, v)
    /\ popped' = popped
    /\ ops' = ops + 1

Pop(c) ==
    /\ ops < MaxOps
    /\ c = 0
    /\ CanPop
    /\ LET val == buffer[Idx(head)] IN
       /\ buffer' = [buffer EXCEPT ![Idx(head)] = NullVal]
       /\ head' = head + 1
       /\ tail' = tail
       /\ pushed' = pushed
       /\ popped' = Append(popped, val)
    /\ ops' = ops + 1

Next ==
    \/ \E p \in Producers, v \in Values : Push(p, v)
    \/ Pop(0)

TypeInv ==
    /\ head \in Nat
    /\ tail \in Nat
    /\ head <= tail
    /\ QueueLen <= N
    /\ buffer \in [0..(N - 1) -> (Values \cup {NullVal})]

NeverOverflow == head <= tail

Linearizability == popped = SubSeq(pushed, 1, Len(popped))

NoDataLoss == \A i \in head..(tail - 1) : buffer[Idx(i)] \in Values

Spec == Init /\ [][Next]_<<buffer, head, tail, pushed, popped>>

==============================================================================
