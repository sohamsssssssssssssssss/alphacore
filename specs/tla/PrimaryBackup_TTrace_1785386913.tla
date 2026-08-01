---- MODULE PrimaryBackup_TTrace_1785386913 ----
EXTENDS Sequences, TLCExt, Toolbox, Naturals, TLC, PrimaryBackup

_expression ==
    LET PrimaryBackup_TEExpression == INSTANCE PrimaryBackup_TEExpression
    IN PrimaryBackup_TEExpression!expression
----

_trace ==
    LET PrimaryBackup_TETrace == INSTANCE PrimaryBackup_TETrace
    IN PrimaryBackup_TETrace!trace
----

_inv ==
    ~(
        TLCGet("level") = Len(_TETrace)
        /\
        committed = ({})
        /\
        n2_journal_seq = (0)
        /\
        n2_state = ()
        /\
        n2_epoch = (1)
        /\
        n2_hb_count = (0)
        /\
        hb_alive = (TRUE)
        /\
        n1_state = ("PRIMARY")
        /\
        active_primary_epoch = (1)
        /\
        n1_journal_seq = (0)
        /\
        network = ({})
        /\
        n1_epoch = (1)
        /\
        n1_hb_count = (0)
    )
----

_init ==
    /\ network = _TETrace[1].network
    /\ n2_journal_seq = _TETrace[1].n2_journal_seq
    /\ n1_epoch = _TETrace[1].n1_epoch
    /\ n2_epoch = _TETrace[1].n2_epoch
    /\ n2_hb_count = _TETrace[1].n2_hb_count
    /\ hb_alive = _TETrace[1].hb_alive
    /\ committed = _TETrace[1].committed
    /\ n1_hb_count = _TETrace[1].n1_hb_count
    /\ active_primary_epoch = _TETrace[1].active_primary_epoch
    /\ n1_state = _TETrace[1].n1_state
    /\ n1_journal_seq = _TETrace[1].n1_journal_seq
    /\ n2_state = _TETrace[1].n2_state
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ network  = _TETrace[i].network
        /\ network' = _TETrace[j].network
        /\ n2_journal_seq  = _TETrace[i].n2_journal_seq
        /\ n2_journal_seq' = _TETrace[j].n2_journal_seq
        /\ n1_epoch  = _TETrace[i].n1_epoch
        /\ n1_epoch' = _TETrace[j].n1_epoch
        /\ n2_epoch  = _TETrace[i].n2_epoch
        /\ n2_epoch' = _TETrace[j].n2_epoch
        /\ n2_hb_count  = _TETrace[i].n2_hb_count
        /\ n2_hb_count' = _TETrace[j].n2_hb_count
        /\ hb_alive  = _TETrace[i].hb_alive
        /\ hb_alive' = _TETrace[j].hb_alive
        /\ committed  = _TETrace[i].committed
        /\ committed' = _TETrace[j].committed
        /\ n1_hb_count  = _TETrace[i].n1_hb_count
        /\ n1_hb_count' = _TETrace[j].n1_hb_count
        /\ active_primary_epoch  = _TETrace[i].active_primary_epoch
        /\ active_primary_epoch' = _TETrace[j].active_primary_epoch
        /\ n1_state  = _TETrace[i].n1_state
        /\ n1_state' = _TETrace[j].n1_state
        /\ n1_journal_seq  = _TETrace[i].n1_journal_seq
        /\ n1_journal_seq' = _TETrace[j].n1_journal_seq
        /\ n2_state  = _TETrace[i].n2_state
        /\ n2_state' = _TETrace[j].n2_state

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("PrimaryBackup_TTrace_1785386913.json", _TETrace)

=============================================================================

 Note that you can extract this module `PrimaryBackup_TEExpression`
  to a dedicated file to reuse `expression` (the module in the 
  dedicated `PrimaryBackup_TEExpression.tla` file takes precedence 
  over the module `PrimaryBackup_TEExpression` below).

---- MODULE PrimaryBackup_TEExpression ----
EXTENDS Sequences, TLCExt, Toolbox, Naturals, TLC, PrimaryBackup

expression == 
    [
        \* To hide variables of the `PrimaryBackup` spec from the error trace,
        \* remove the variables below.  The trace will be written in the order
        \* of the fields of this record.
        network |-> network
        ,n2_journal_seq |-> n2_journal_seq
        ,n1_epoch |-> n1_epoch
        ,n2_epoch |-> n2_epoch
        ,n2_hb_count |-> n2_hb_count
        ,hb_alive |-> hb_alive
        ,committed |-> committed
        ,n1_hb_count |-> n1_hb_count
        ,active_primary_epoch |-> active_primary_epoch
        ,n1_state |-> n1_state
        ,n1_journal_seq |-> n1_journal_seq
        ,n2_state |-> n2_state
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_networkUnchanged |-> network = network'
        
        \* Format the `network` variable as Json value.
        \* ,_networkJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(network)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_networkModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].network # _TETrace[s-1].network
        \*             THEN 1 + F[s-1] ELSE F[s-1]
        \*     IN F[_TEPosition - 1]
    ]

=============================================================================



Parsing and semantic processing can take forever if the trace below is long.
 In this case, it is advised to uncomment the module below to deserialize the
 trace from a generated binary file.

\*
\*---- MODULE PrimaryBackup_TETrace ----
\*EXTENDS IOUtils, TLC, PrimaryBackup
\*
\*trace == IODeserialize("PrimaryBackup_TTrace_1785386913.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE PrimaryBackup_TETrace ----
EXTENDS TLC, PrimaryBackup

trace == 
    <<
    ([committed |-> {},n2_journal_seq |-> 0,n2_state |-> "UNKNOWN",n2_epoch |-> 0,n2_hb_count |-> 0,hb_alive |-> TRUE,n1_state |-> "UNKNOWN",active_primary_epoch |-> 0,n1_journal_seq |-> 0,network |-> {},n1_epoch |-> 0,n1_hb_count |-> 0]),
    ([committed |-> {},n2_journal_seq |-> 0,n2_state |-> "UNKNOWN",n2_epoch |-> 0,n2_hb_count |-> 0,hb_alive |-> TRUE,n1_state |-> "PRIMARY",active_primary_epoch |-> 1,n1_journal_seq |-> 0,network |-> {},n1_epoch |-> 1,n1_hb_count |-> 0]),
    ([committed |-> {},n2_journal_seq |-> 0,n2_state |-> "BACKUP",n2_epoch |-> 1,n2_hb_count |-> 0,hb_alive |-> TRUE,n1_state |-> "PRIMARY",active_primary_epoch |-> 1,n1_journal_seq |-> 0,network |-> {},n1_epoch |-> 1,n1_hb_count |-> 0]),
    ([committed |-> {},n2_journal_seq |-> 0,n2_state |-> "BACKUP",n2_epoch |-> 1,n2_hb_count |-> 0,hb_alive |-> TRUE,n1_state |-> "PRIMARY",active_primary_epoch |-> 1,n1_journal_seq |-> 0,network |-> {[type |-> "HEARTBEAT", src |-> "N1", epoch |-> 1, seq |-> 0, payload |-> 0]},n1_epoch |-> 1,n1_hb_count |-> 0]),
    ([committed |-> {},n2_journal_seq |-> 0,n2_state |-> ,n2_epoch |-> 1,n2_hb_count |-> 0,hb_alive |-> TRUE,n1_state |-> "PRIMARY",active_primary_epoch |-> 1,n1_journal_seq |-> 0,network |-> {},n1_epoch |-> 1,n1_hb_count |-> 0])
    >>
----


=============================================================================

---- CONFIG PrimaryBackup_TTrace_1785386913 ----
CONSTANTS
    MaxEntries = 3
    HeartbeatTimeout = 2
    MaxMessages = 5

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
\* Generated on Thu Jul 30 10:18:33 IST 2026