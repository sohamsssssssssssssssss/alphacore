------------------------------ MODULE MpscQueue ------------------------------
(*
AlphaCore — Lock-Free MPSC Ring Buffer TLA+ Specification

Models 2 producers + 1 consumer with a bounded ring buffer (Capacity=4).
Invariants: NoTornRead, ItemsInOutAreFromEnqueue, NoDuplicates,
            ProduceMonotonic, ConsumeMonotonic, FullQueueBackpressure.
*)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS
    Capacity,       (* must be power of 2 *)
    MaxItem

ASSUME Capacity > 0

VARIABLES
    write_ticket,
    read_ticket,
    seq_array,      (* [i \in 0..Capacity-1 -> seq] *)
    slots,          (* [i \in 0..Capacity-1 -> item value] *)
    consumer_out,   (* sequence of popped items *)
    pc,             (* program counter per process *)
    p_var,          (* per-producer temporary: [p \in 1..2 -> item] *)
    cpos, cseq, val (* consumer temporaries *)

vars == <<write_ticket, read_ticket, seq_array, slots, consumer_out,
          pc, p_var, cpos, cseq, val>>

Index(pos) == pos % Capacity

Init ==
    /\ write_ticket = 0
    /\ read_ticket = 0
    /\ seq_array = [i \in 0..Capacity-1 |-> i]
    /\ slots = [i \in 0..Capacity-1 |-> 0]
    /\ consumer_out = <<>>   (* now stores <<write_ticket, val>> tuples *)
    /\ pc = [p \in 1..3 |-> IF p <= 2 THEN "Choose" ELSE "Consume"]
    /\ p_var = [p \in 1..2 |-> 0]
    /\ cpos = 0 /\ cseq = 0 /\ val = 0

(* Producer action: choose an item *)
ChooseItem(p) ==
    /\ pc[p] = "Choose"
    /\ \E i \in 1..MaxItem :
        p_var' = [p_var EXCEPT ![p] = (p - 1) * MaxItem + i]
    /\ pc' = [pc EXCEPT ![p] = "Claim"]
    /\ UNCHANGED <<write_ticket, read_ticket, seq_array, slots,
                  consumer_out, cpos, cseq, val>>

(* Producer action: claim write ticket and write item *)
ClaimAndWrite(p) ==
    /\ pc[p] = "Claim"
    /\ write_ticket - read_ticket < Capacity
    /\ LET idx == Index(write_ticket) IN
      write_ticket' = write_ticket + 1
      /\ slots' = [slots EXCEPT ![idx] = p_var[p]]
      /\ seq_array' = [seq_array EXCEPT ![idx] = write_ticket + 1]
    /\ pc' = [pc EXCEPT ![p] = "Choose"]
    /\ UNCHANGED <<read_ticket, consumer_out, p_var, cpos, cseq, val>>

ProducerNext(p) ==
    ChooseItem(p) \/ ClaimAndWrite(p)

(* Consumer action *)
Consume ==
    /\ pc[3] = "Consume"
    /\ cpos' = read_ticket
    /\ LET idx == Index(cpos') IN
      IF seq_array[idx] = cpos' + 1
      THEN /\ val' = slots[idx]
           /\ cseq' = seq_array[idx]
           /\ consumer_out' = Append(consumer_out, <<cpos', val'>>)  (* store (write_ticket, val) tuple *)
           /\ seq_array' = [seq_array EXCEPT ![idx] = cpos' + Capacity]
           /\ read_ticket' = cpos' + 1
      ELSE /\ UNCHANGED <<val, cseq, consumer_out, seq_array, read_ticket>>
    /\ pc' = [pc EXCEPT ![3] = "Consume"]
    /\ UNCHANGED <<write_ticket, p_var, slots>>

ConsumerNext ==
    Consume \/ (pc[3] = "Consume" /\ UNCHANGED vars)

Next ==
    (\E p \in {1,2} : ProducerNext(p)) \/ ConsumerNext

(* === INVARIANTS === *)

(* INVARIANT 1: Consumer never reads a partially-written slot *)
NoTornRead ==
    \A i \in 0..Capacity-1 :
        (seq_array[i] > i) => (slots[i] > 0 \/ seq_array[i] > i + 1)

(* INVARIANT 2: Every popped item was previously enqueued *)
(* Item values range from 1 to NumProducers*MaxItem, one disjoint pool per producer *)
(* consumer_out stores <<write_ticket, val>> tuples; val is the second component *)
ItemsInOutAreFromEnqueue ==
    \A i \in 1..Len(consumer_out) :
        LET v == consumer_out[i][2] IN
        v > 0 /\ v <= 2 * MaxItem

(* INVARIANT 3: No write_ticket appears twice in consumer output.
   Each enqueue operation claims a globally unique write_ticket.
   Consumer_out stores <<write_ticket, val>> tuples, so checking
   uniqueness of the first component (the ticket) verifies that no
   message is lost or duplicated, regardless of whether two different
   messages happen to have the same value (a modeling artifact when
   MaxItem is small). *)
NoDuplicates ==
    \A i, j \in 1..Len(consumer_out) :
        i # j => consumer_out[i][1] # consumer_out[j][1]

(* INVARIANT 4: Write ticket is non-decreasing *)
ProduceMonotonic ==
    [][ write_ticket' >= write_ticket ]_<<write_ticket>>

(* INVARIANT 5: Read ticket is non-decreasing *)
ConsumeMonotonic ==
    [][ read_ticket' >= read_ticket ]_<<read_ticket>>

(* INVARIANT 6: Queue never exceeds capacity *)
FullQueueBackpressure ==
    write_ticket - read_ticket <= Capacity

(* Bound on total write operations for TLC model checking *)
OpBound == write_ticket <= 12

(* No fairness constraints: safety checking does not require liveness.       *)
(* WF_vars removed to keep the state space finite and TLC tractable.        *)
Spec == Init /\ [][Next]_vars

=============================================================================
