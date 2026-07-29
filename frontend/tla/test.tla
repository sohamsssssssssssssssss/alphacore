-- module Test
CONSTANT A
VARIABLES x
Init == x = 0
Spec == Init /\\ [][(x' = (x + 1) % A)]_x
======================================================================
