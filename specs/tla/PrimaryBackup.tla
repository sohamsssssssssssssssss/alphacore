------------------------------ MODULE PrimaryBackup ------------------------------
(*
AlphaCore — Primary-Backup HA with Epoch-Based Leader Fencing

Models 2 nodes (N1, N2) with PRIMARY/BACKUP/UNKNOWN roles, epoch-based
fencing, heartbeat timeout, log replication, and network faults.

Invariants: AtMostOneLeader, ActiveEpochUnique, NoSplitBrain,
            PromotionOnlyOnTimeout, CommittedDataSafe, EpochFencing.
*)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS
    MaxEntries,       (* maximum journal entries *)
    HeartbeatTimeout, (* missed heartbeats before promotion *)
    MaxMessages       (* bound on in-flight messages *)

ASSUME HeartbeatTimeout > 0

MessageType == {"HEARTBEAT", "LOG_ENTRY", "EPOCH_NOTIFY", "ACK"}

Message == [type : MessageType,
            src  : {"N1", "N2"},
            epoch: 0..MaxEntries,
            seq  : 0..MaxEntries,
            payload : 0..MaxEntries]

VARIABLES
    n1_state, n2_state,          (* node roles *)
    n1_epoch, n2_epoch,          (* current epochs *)
    n1_journal_seq, n2_journal_seq,
    n1_hb_count, n2_hb_count,    (* missed heartbeat counters *)
    hb_alive,                    (* is heartbeat sender alive *)
    network,                     (* in-flight messages *)
    committed,                   (* set of (epoch, seq) tuples *)
    active_primary_epoch

vars == <<n1_state, n2_state, n1_epoch, n2_epoch,
          n1_journal_seq, n2_journal_seq,
          n1_hb_count, n2_hb_count,
          hb_alive, network, committed, active_primary_epoch>>

Init ==
    /\ n1_state = "UNKNOWN" /\ n2_state = "UNKNOWN"
    /\ n1_epoch = 0 /\ n2_epoch = 0
    /\ n1_journal_seq = 0 /\ n2_journal_seq = 0
    /\ n1_hb_count = 0 /\ n2_hb_count = 0
    /\ hb_alive = TRUE
    /\ network = {}
    /\ committed = {}
    /\ active_primary_epoch = 0

(* ---- ACTIONS ---- *)

BootPrimary ==
    /\ n1_state = "UNKNOWN"
    /\ n2_state # "PRIMARY"
    /\ n1_state' = "PRIMARY"
    /\ n1_epoch' = 1
    /\ active_primary_epoch' = 1
    /\ UNCHANGED <<n2_state, n2_epoch, n1_journal_seq, n2_journal_seq,
                  n1_hb_count, n2_hb_count,
                  hb_alive, network, committed>>

BootBackup ==
    /\ n2_state = "UNKNOWN"
    /\ n2_state' = "BACKUP"
    /\ n2_epoch' = n1_epoch
    /\ UNCHANGED <<n1_state, n1_epoch, n1_journal_seq, n2_journal_seq,
                  n1_hb_count, n2_hb_count,
                  hb_alive, network, committed, active_primary_epoch>>

PrimarySendHeartbeat ==
    /\ n1_state = "PRIMARY"
    /\ network' = network \cup {[type |-> "HEARTBEAT", src |-> "N1",
                                epoch |-> n1_epoch, seq |-> n1_journal_seq,
                                payload |-> 0]}
    /\ UNCHANGED <<n1_state, n2_state, n1_epoch, n2_epoch,
                  n1_journal_seq, n2_journal_seq,
                  n1_hb_count, n2_hb_count,
                  hb_alive, committed, active_primary_epoch>>

BackupReceiveHeartbeat ==
    /\ \E msg \in network :
        msg.type = "HEARTBEAT" /\ msg.src = "N1" /\ n2_state = "BACKUP"
    /\ LET msg == CHOOSE m \in network : m.type = "HEARTBEAT" /\ m.src = "N1" IN
       /\ n2_hb_count' = 0
       /\ n2_epoch' = msg.epoch
       /\ network' = network \ {msg}
    /\ UNCHANGED <<n1_state, n2_state, n1_epoch, n2_journal_seq, n1_journal_seq,
                  n1_hb_count, hb_alive, committed, active_primary_epoch>>

BackupMissHeartbeat ==
    /\ n2_state = "BACKUP"
    /\ n2_hb_count' = n2_hb_count + 1
    /\ UNCHANGED <<n1_state, n2_state, n1_epoch, n2_epoch,
                  n1_journal_seq, n2_journal_seq,
                  n1_hb_count, hb_alive, network, committed, active_primary_epoch>>

BackupPromote ==
    /\ n2_state = "BACKUP"
    /\ n2_hb_count >= HeartbeatTimeout
    /\ n2_epoch' = n2_epoch + 1
    /\ n2_state' = "PRIMARY"
    /\ n2_hb_count' = 0
    /\ active_primary_epoch' = n2_epoch'
    /\ n1_state' = "UNKNOWN"
    /\ UNCHANGED <<n1_epoch, n1_journal_seq, n2_journal_seq,
                  n1_hb_count, hb_alive, network, committed>>

PrimarySendEpochNotify ==
    /\ (n1_state = "PRIMARY" \/ n2_state = "PRIMARY")
    /\ LET src == IF n1_state = "PRIMARY" THEN "N1" ELSE "N2"
           current_epoch == IF src = "N1" THEN n1_epoch ELSE n2_epoch IN
       network' = network \cup {[type |-> "EPOCH_NOTIFY", src |-> src,
                                epoch |-> current_epoch, seq |-> 0, payload |-> 0]}
    /\ UNCHANGED <<n1_state, n2_state, n1_epoch, n2_epoch,
                  n1_journal_seq, n2_journal_seq,
                  n1_hb_count, n2_hb_count,
                  hb_alive, committed, active_primary_epoch>>

ReceiveEpochNotify ==
    /\ \E msg \in network : msg.type = "EPOCH_NOTIFY"
    /\ LET msg == CHOOSE m \in network : m.type = "EPOCH_NOTIFY" IN
       /\ IF msg.src = "N1" /\ msg.epoch >= n2_epoch
          THEN /\ n2_epoch' = msg.epoch
               /\ IF n2_state = "PRIMARY" /\ msg.epoch > n2_epoch
                  THEN n2_state' = "BACKUP"
                  ELSE UNCHANGED n2_state
               /\ UNCHANGED <<n1_state, n1_epoch>>
          ELSE IF msg.src = "N2" /\ msg.epoch >= n1_epoch
          THEN /\ n1_epoch' = msg.epoch
               /\ IF n1_state = "PRIMARY" /\ msg.epoch > n1_epoch
                  THEN n1_state' = "BACKUP"
                  ELSE UNCHANGED n1_state
               /\ UNCHANGED <<n2_state, n2_epoch>>
          ELSE UNCHANGED <<n1_state, n2_state, n1_epoch, n2_epoch>>
       /\ network' = network \ {msg}
    /\ UNCHANGED <<n1_journal_seq, n2_journal_seq,
                  n1_hb_count, n2_hb_count,
                  hb_alive, committed, active_primary_epoch>>

PrimaryAppendLog ==
    /\ n1_state = "PRIMARY"
    /\ n1_journal_seq < MaxEntries
    /\ n1_journal_seq' = n1_journal_seq + 1
    /\ network' = network \cup {[type |-> "LOG_ENTRY", src |-> "N1",
                                epoch |-> n1_epoch, seq |-> n1_journal_seq + 1,
                                payload |-> n1_journal_seq + 1]}
    /\ UNCHANGED <<n1_state, n2_state, n1_epoch, n2_epoch,
                  n2_journal_seq, n1_hb_count, n2_hb_count,
                  hb_alive, committed, active_primary_epoch>>

BackupApplyLog ==
    /\ \E msg \in network :
        msg.type = "LOG_ENTRY" /\ msg.src = "N1"
    /\ LET msg == CHOOSE m \in network : m.type = "LOG_ENTRY" /\ m.src = "N1" IN
       /\ IF msg.epoch >= n2_epoch
          THEN /\ n2_journal_seq' = msg.seq
               /\ committed' = committed \cup {<<msg.epoch, msg.seq>>}
          ELSE UNCHANGED <<n2_journal_seq, committed>>
       /\ network' = network \ {msg}
    /\ UNCHANGED <<n1_state, n2_state, n1_epoch, n2_epoch,
                  n1_journal_seq, n1_hb_count, n2_hb_count,
                  hb_alive, active_primary_epoch>>

DropMessage ==
    /\ network # {}
    /\ \E msg \in network : network' = network \ {msg}
    /\ UNCHANGED <<n1_state, n2_state, n1_epoch, n2_epoch,
                  n1_journal_seq, n2_journal_seq,
                  n1_hb_count, n2_hb_count,
                  hb_alive, committed, active_primary_epoch>>

HeartbeatFailure ==
    /\ hb_alive = TRUE /\ hb_alive' = FALSE
    /\ UNCHANGED <<n1_state, n2_state, n1_epoch, n2_epoch,
                  n1_journal_seq, n2_journal_seq,
                  n1_hb_count, n2_hb_count, network, committed,
                  active_primary_epoch>>

HeartbeatRestore ==
    /\ hb_alive = FALSE /\ hb_alive' = TRUE
    /\ UNCHANGED <<n1_state, n2_state, n1_epoch, n2_epoch,
                  n1_journal_seq, n2_journal_seq,
                  n1_hb_count, n2_hb_count, network, committed,
                  active_primary_epoch>>

Next ==
    \/ BootPrimary \/ BootBackup
    \/ PrimarySendHeartbeat \/ BackupReceiveHeartbeat
    \/ BackupMissHeartbeat \/ BackupPromote
    \/ PrimarySendEpochNotify \/ ReceiveEpochNotify
    \/ PrimaryAppendLog \/ BackupApplyLog
    \/ DropMessage \/ HeartbeatFailure \/ HeartbeatRestore

(* ---- INVARIANTS ---- *)

AtMostOneLeader ==
    ~ (n1_state = "PRIMARY" /\ n2_state = "PRIMARY")

ActiveEpochUnique ==
    (n1_state = "PRIMARY" => n1_epoch = active_primary_epoch) /\
    (n2_state = "PRIMARY" => n2_epoch = active_primary_epoch)

NoSplitBrain ==
    \A <<ep, _s>> \in committed :
        active_primary_epoch >= ep

PromotionOnlyOnTimeout ==
    [][ (n2_state' = "PRIMARY" /\ n2_state = "BACKUP")
         => n2_hb_count >= HeartbeatTimeout ]_<<n2_state, n2_hb_count>>

CommittedDataSafe ==
    [][ committed \subseteq committed' ]_<<committed>>

EpochFencing ==
    [][ \A msg \in network :
            (msg.type = "LOG_ENTRY" /\ msg.src = "N1" /\ msg.epoch < n2_epoch)
            => UNCHANGED n2_journal_seq
      ]_<<n2_journal_seq, network>>

(* Bounds for TLC model checking *)
JournalOpBound == n1_journal_seq + n2_journal_seq <= 6
ActionBound == n1_hb_count + n2_hb_count + Cardinality(network) <= 8

Spec == Init /\ [][Next]_vars

=============================================================================
