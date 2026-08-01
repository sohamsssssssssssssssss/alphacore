---- MODULE MpscQueue_TTrace_1785387788 ----
EXTENDS Sequences, TLCExt, Toolbox, Naturals, TLC, MpscQueue

_expression ==
    LET MpscQueue_TEExpression == INSTANCE MpscQueue_TEExpression
    IN MpscQueue_TEExpression!expression
----

_trace ==
    LET MpscQueue_TETrace == INSTANCE MpscQueue_TETrace
    IN MpscQueue_TETrace!trace
----

_inv ==
    ~(
        TLCGet("level") = Len(_TETrace)
        /\
        head = (4)
        /\
        popped = (<<0, 0, 0, 0>>)
        /\
        ops = (16)
        /\
        tail = (12)
        /\
        buffer = ((0 :> 0 @@ 1 :> 0 @@ 2 :> 0 @@ 3 :> 0 @@ 4 :> 0 @@ 5 :> 0 @@ 6 :> 0 @@ 7 :> 0))
        /\
        pushed = (<<0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0>>)
    )
----

_init ==
    /\ ops = _TETrace[1].ops
    /\ buffer = _TETrace[1].buffer
    /\ tail = _TETrace[1].tail
    /\ head = _TETrace[1].head
    /\ pushed = _TETrace[1].pushed
    /\ popped = _TETrace[1].popped
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ ops  = _TETrace[i].ops
        /\ ops' = _TETrace[j].ops
        /\ buffer  = _TETrace[i].buffer
        /\ buffer' = _TETrace[j].buffer
        /\ tail  = _TETrace[i].tail
        /\ tail' = _TETrace[j].tail
        /\ head  = _TETrace[i].head
        /\ head' = _TETrace[j].head
        /\ pushed  = _TETrace[i].pushed
        /\ pushed' = _TETrace[j].pushed
        /\ popped  = _TETrace[i].popped
        /\ popped' = _TETrace[j].popped

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("MpscQueue_TTrace_1785387788.json", _TETrace)

=============================================================================

 Note that you can extract this module `MpscQueue_TEExpression`
  to a dedicated file to reuse `expression` (the module in the 
  dedicated `MpscQueue_TEExpression.tla` file takes precedence 
  over the module `MpscQueue_TEExpression` below).

---- MODULE MpscQueue_TEExpression ----
EXTENDS Sequences, TLCExt, Toolbox, Naturals, TLC, MpscQueue

expression == 
    [
        \* To hide variables of the `MpscQueue` spec from the error trace,
        \* remove the variables below.  The trace will be written in the order
        \* of the fields of this record.
        ops |-> ops
        ,buffer |-> buffer
        ,tail |-> tail
        ,head |-> head
        ,pushed |-> pushed
        ,popped |-> popped
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_opsUnchanged |-> ops = ops'
        
        \* Format the `ops` variable as Json value.
        \* ,_opsJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(ops)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_opsModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].ops # _TETrace[s-1].ops
        \*             THEN 1 + F[s-1] ELSE F[s-1]
        \*     IN F[_TEPosition - 1]
    ]

=============================================================================



Parsing and semantic processing can take forever if the trace below is long.
 In this case, it is advised to uncomment the module below to deserialize the
 trace from a generated binary file.

\*
\*---- MODULE MpscQueue_TETrace ----
\*EXTENDS IOUtils, TLC, MpscQueue
\*
\*trace == IODeserialize("MpscQueue_TTrace_1785387788.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE MpscQueue_TETrace ----
EXTENDS TLC, MpscQueue

trace == 
    <<
    ([head |-> 0,popped |-> <<>>,ops |-> 0,tail |-> 0,buffer |-> (0 :> -1 @@ 1 :> -1 @@ 2 :> -1 @@ 3 :> -1 @@ 4 :> -1 @@ 5 :> -1 @@ 6 :> -1 @@ 7 :> -1),pushed |-> <<>>]),
    ([head |-> 0,popped |-> <<>>,ops |-> 1,tail |-> 1,buffer |-> (0 :> 0 @@ 1 :> -1 @@ 2 :> -1 @@ 3 :> -1 @@ 4 :> -1 @@ 5 :> -1 @@ 6 :> -1 @@ 7 :> -1),pushed |-> <<0>>]),
    ([head |-> 0,popped |-> <<>>,ops |-> 2,tail |-> 2,buffer |-> (0 :> 0 @@ 1 :> 0 @@ 2 :> -1 @@ 3 :> -1 @@ 4 :> -1 @@ 5 :> -1 @@ 6 :> -1 @@ 7 :> -1),pushed |-> <<0, 0>>]),
    ([head |-> 0,popped |-> <<>>,ops |-> 3,tail |-> 3,buffer |-> (0 :> 0 @@ 1 :> 0 @@ 2 :> 0 @@ 3 :> -1 @@ 4 :> -1 @@ 5 :> -1 @@ 6 :> -1 @@ 7 :> -1),pushed |-> <<0, 0, 0>>]),
    ([head |-> 0,popped |-> <<>>,ops |-> 4,tail |-> 4,buffer |-> (0 :> 0 @@ 1 :> 0 @@ 2 :> 0 @@ 3 :> 0 @@ 4 :> -1 @@ 5 :> -1 @@ 6 :> -1 @@ 7 :> -1),pushed |-> <<0, 0, 0, 0>>]),
    ([head |-> 0,popped |-> <<>>,ops |-> 5,tail |-> 5,buffer |-> (0 :> 0 @@ 1 :> 0 @@ 2 :> 0 @@ 3 :> 0 @@ 4 :> 0 @@ 5 :> -1 @@ 6 :> -1 @@ 7 :> -1),pushed |-> <<0, 0, 0, 0, 0>>]),
    ([head |-> 0,popped |-> <<>>,ops |-> 6,tail |-> 6,buffer |-> (0 :> 0 @@ 1 :> 0 @@ 2 :> 0 @@ 3 :> 0 @@ 4 :> 0 @@ 5 :> 0 @@ 6 :> -1 @@ 7 :> -1),pushed |-> <<0, 0, 0, 0, 0, 0>>]),
    ([head |-> 0,popped |-> <<>>,ops |-> 7,tail |-> 7,buffer |-> (0 :> 0 @@ 1 :> 0 @@ 2 :> 0 @@ 3 :> 0 @@ 4 :> 0 @@ 5 :> 0 @@ 6 :> 0 @@ 7 :> -1),pushed |-> <<0, 0, 0, 0, 0, 0, 0>>]),
    ([head |-> 0,popped |-> <<>>,ops |-> 8,tail |-> 8,buffer |-> (0 :> 0 @@ 1 :> 0 @@ 2 :> 0 @@ 3 :> 0 @@ 4 :> 0 @@ 5 :> 0 @@ 6 :> 0 @@ 7 :> 0),pushed |-> <<0, 0, 0, 0, 0, 0, 0, 0>>]),
    ([head |-> 1,popped |-> <<0>>,ops |-> 9,tail |-> 8,buffer |-> (0 :> -1 @@ 1 :> 0 @@ 2 :> 0 @@ 3 :> 0 @@ 4 :> 0 @@ 5 :> 0 @@ 6 :> 0 @@ 7 :> 0),pushed |-> <<0, 0, 0, 0, 0, 0, 0, 0>>]),
    ([head |-> 1,popped |-> <<0>>,ops |-> 10,tail |-> 9,buffer |-> (0 :> 0 @@ 1 :> 0 @@ 2 :> 0 @@ 3 :> 0 @@ 4 :> 0 @@ 5 :> 0 @@ 6 :> 0 @@ 7 :> 0),pushed |-> <<0, 0, 0, 0, 0, 0, 0, 0, 0>>]),
    ([head |-> 2,popped |-> <<0, 0>>,ops |-> 11,tail |-> 9,buffer |-> (0 :> 0 @@ 1 :> -1 @@ 2 :> 0 @@ 3 :> 0 @@ 4 :> 0 @@ 5 :> 0 @@ 6 :> 0 @@ 7 :> 0),pushed |-> <<0, 0, 0, 0, 0, 0, 0, 0, 0>>]),
    ([head |-> 2,popped |-> <<0, 0>>,ops |-> 12,tail |-> 10,buffer |-> (0 :> 0 @@ 1 :> 0 @@ 2 :> 0 @@ 3 :> 0 @@ 4 :> 0 @@ 5 :> 0 @@ 6 :> 0 @@ 7 :> 0),pushed |-> <<0, 0, 0, 0, 0, 0, 0, 0, 0, 0>>]),
    ([head |-> 3,popped |-> <<0, 0, 0>>,ops |-> 13,tail |-> 10,buffer |-> (0 :> 0 @@ 1 :> 0 @@ 2 :> -1 @@ 3 :> 0 @@ 4 :> 0 @@ 5 :> 0 @@ 6 :> 0 @@ 7 :> 0),pushed |-> <<0, 0, 0, 0, 0, 0, 0, 0, 0, 0>>]),
    ([head |-> 3,popped |-> <<0, 0, 0>>,ops |-> 14,tail |-> 11,buffer |-> (0 :> 0 @@ 1 :> 0 @@ 2 :> 0 @@ 3 :> 0 @@ 4 :> 0 @@ 5 :> 0 @@ 6 :> 0 @@ 7 :> 0),pushed |-> <<0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0>>]),
    ([head |-> 4,popped |-> <<0, 0, 0, 0>>,ops |-> 15,tail |-> 11,buffer |-> (0 :> 0 @@ 1 :> 0 @@ 2 :> 0 @@ 3 :> -1 @@ 4 :> 0 @@ 5 :> 0 @@ 6 :> 0 @@ 7 :> 0),pushed |-> <<0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0>>]),
    ([head |-> 4,popped |-> <<0, 0, 0, 0>>,ops |-> 16,tail |-> 12,buffer |-> (0 :> 0 @@ 1 :> 0 @@ 2 :> 0 @@ 3 :> 0 @@ 4 :> 0 @@ 5 :> 0 @@ 6 :> 0 @@ 7 :> 0),pushed |-> <<0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0>>])
    >>
----


=============================================================================

---- CONFIG MpscQueue_TTrace_1785387788 ----
CONSTANTS
    N = 8
    NumProducers = 2
    Values = { 0 , 1 , 2 , 3 }
    MaxOps = 16

INVARIANT
    _inv

CHECK_DEADLOCK
    \* CHECK_DEADLOCK off because of PROPERTY or INVARIANT above.
    FALSE

INIT
    _init

NEXT
    _next

CONSTANT
    _TETrace <- _trace

ALIAS
    _expression
=============================================================================
\* Generated on Thu Jul 30 10:35:32 IST 2026