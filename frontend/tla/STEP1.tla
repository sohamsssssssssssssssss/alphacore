---------------------------- MODULE Spec -----------------------------
EXTENDS Naturals

CONSTANTS A, B

VARIABLES x

Init == x = 0
Next == x' = (x + 1) % A
Spec == Init /\\ [][Next]_x

======================================================================
