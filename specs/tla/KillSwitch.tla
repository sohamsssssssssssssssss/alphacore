----------------------------- MODULE KillSwitch ------------------------------
EXTENDS Booleans

VARIABLES kill_switch_active, signals_allowed

Init ==
  /\ kill_switch_active = FALSE
  /\ signals_allowed = TRUE

Activate ==
  /\ kill_switch_active' = TRUE
  /\ signals_allowed' = FALSE

Deactivate ==
  /\ kill_switch_active' = FALSE
  /\ signals_allowed' = TRUE

Next == Activate \/ Deactivate

Invariant == kill_switch_active => signals_allowed = FALSE

Spec == Init /\ [][Next]_<<kill_switch_active, signals_allowed>>
=============================================================================
