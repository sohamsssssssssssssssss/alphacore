---- MODULE MpscQueue_TTrace_1785387172 ----
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
        val = (1)
        /\
        write_ticket = (2)
        /\
        cseq = (2)
        /\
        slots = ((0 :> 1 @@ 1 :> 1 @@ 2 :> 0 @@ 3 :> 0))
        /\
        consumer_out = (<<1, 1>>)
        /\
        pc = (<<"Choose", "Choose", "Consume">>)
        /\
        seq_array = ((0 :> 4 @@ 1 :> 5 @@ 2 :> 2 @@ 3 :> 3))
        /\
        read_ticket = (2)
        /\
        cpos = (1)
        /\
        p_var = (<<1, 0>>)
    )
----

_init ==
    /\ cseq = _TETrace[1].cseq
    /\ val = _TETrace[1].val
    /\ cpos = _TETrace[1].cpos
    /\ consumer_out = _TETrace[1].consumer_out
    /\ seq_array = _TETrace[1].seq_array
    /\ p_var = _TETrace[1].p_var
    /\ pc = _TETrace[1].pc
    /\ slots = _TETrace[1].slots
    /\ read_ticket = _TETrace[1].read_ticket
    /\ write_ticket = _TETrace[1].write_ticket
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ cseq  = _TETrace[i].cseq
        /\ cseq' = _TETrace[j].cseq
        /\ val  = _TETrace[i].val
        /\ val' = _TETrace[j].val
        /\ cpos  = _TETrace[i].cpos
        /\ cpos' = _TETrace[j].cpos
        /\ consumer_out  = _TETrace[i].consumer_out
        /\ consumer_out' = _TETrace[j].consumer_out
        /\ seq_array  = _TETrace[i].seq_array
        /\ seq_array' = _TETrace[j].seq_array
        /\ p_var  = _TETrace[i].p_var
        /\ p_var' = _TETrace[j].p_var
        /\ pc  = _TETrace[i].pc
        /\ pc' = _TETrace[j].pc
        /\ slots  = _TETrace[i].slots
        /\ slots' = _TETrace[j].slots
        /\ read_ticket  = _TETrace[i].read_ticket
        /\ read_ticket' = _TETrace[j].read_ticket
        /\ write_ticket  = _TETrace[i].write_ticket
        /\ write_ticket' = _TETrace[j].write_ticket

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("MpscQueue_TTrace_1785387172.json", _TETrace)

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
        cseq |-> cseq
        ,val |-> val
        ,cpos |-> cpos
        ,consumer_out |-> consumer_out
        ,seq_array |-> seq_array
        ,p_var |-> p_var
        ,pc |-> pc
        ,slots |-> slots
        ,read_ticket |-> read_ticket
        ,write_ticket |-> write_ticket
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_cseqUnchanged |-> cseq = cseq'
        
        \* Format the `cseq` variable as Json value.
        \* ,_cseqJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(cseq)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_cseqModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].cseq # _TETrace[s-1].cseq
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
\*trace == IODeserialize("MpscQueue_TTrace_1785387172.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE MpscQueue_TETrace ----
EXTENDS TLC, MpscQueue

trace == 
    <<
    ([val |-> 0,write_ticket |-> 0,cseq |-> 0,slots |-> (0 :> 0 @@ 1 :> 0 @@ 2 :> 0 @@ 3 :> 0),consumer_out |-> <<>>,pc |-> <<"Choose", "Choose", "Consume">>,seq_array |-> (0 :> 0 @@ 1 :> 1 @@ 2 :> 2 @@ 3 :> 3),read_ticket |-> 0,cpos |-> 0,p_var |-> <<0, 0>>]),
    ([val |-> 0,write_ticket |-> 0,cseq |-> 0,slots |-> (0 :> 0 @@ 1 :> 0 @@ 2 :> 0 @@ 3 :> 0),consumer_out |-> <<>>,pc |-> <<"Claim", "Choose", "Consume">>,seq_array |-> (0 :> 0 @@ 1 :> 1 @@ 2 :> 2 @@ 3 :> 3),read_ticket |-> 0,cpos |-> 0,p_var |-> <<1, 0>>]),
    ([val |-> 0,write_ticket |-> 1,cseq |-> 0,slots |-> (0 :> 1 @@ 1 :> 0 @@ 2 :> 0 @@ 3 :> 0),consumer_out |-> <<>>,pc |-> <<"Choose", "Choose", "Consume">>,seq_array |-> (0 :> 1 @@ 1 :> 1 @@ 2 :> 2 @@ 3 :> 3),read_ticket |-> 0,cpos |-> 0,p_var |-> <<1, 0>>]),
    ([val |-> 0,write_ticket |-> 1,cseq |-> 0,slots |-> (0 :> 1 @@ 1 :> 0 @@ 2 :> 0 @@ 3 :> 0),consumer_out |-> <<>>,pc |-> <<"Claim", "Choose", "Consume">>,seq_array |-> (0 :> 1 @@ 1 :> 1 @@ 2 :> 2 @@ 3 :> 3),read_ticket |-> 0,cpos |-> 0,p_var |-> <<1, 0>>]),
    ([val |-> 0,write_ticket |-> 2,cseq |-> 0,slots |-> (0 :> 1 @@ 1 :> 1 @@ 2 :> 0 @@ 3 :> 0),consumer_out |-> <<>>,pc |-> <<"Choose", "Choose", "Consume">>,seq_array |-> (0 :> 1 @@ 1 :> 2 @@ 2 :> 2 @@ 3 :> 3),read_ticket |-> 0,cpos |-> 0,p_var |-> <<1, 0>>]),
    ([val |-> 1,write_ticket |-> 2,cseq |-> 1,slots |-> (0 :> 1 @@ 1 :> 1 @@ 2 :> 0 @@ 3 :> 0),consumer_out |-> <<1>>,pc |-> <<"Choose", "Choose", "Consume">>,seq_array |-> (0 :> 4 @@ 1 :> 2 @@ 2 :> 2 @@ 3 :> 3),read_ticket |-> 1,cpos |-> 0,p_var |-> <<1, 0>>]),
    ([val |-> 1,write_ticket |-> 2,cseq |-> 2,slots |-> (0 :> 1 @@ 1 :> 1 @@ 2 :> 0 @@ 3 :> 0),consumer_out |-> <<1, 1>>,pc |-> <<"Choose", "Choose", "Consume">>,seq_array |-> (0 :> 4 @@ 1 :> 5 @@ 2 :> 2 @@ 3 :> 3),read_ticket |-> 2,cpos |-> 1,p_var |-> <<1, 0>>])
    >>
----


=============================================================================

---- CONFIG MpscQueue_TTrace_1785387172 ----
CONSTANTS
    Capacity = 4
    MaxItem = 3

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
\* Generated on Thu Jul 30 10:22:52 IST 2026