# Amendment 2 to the 12-1 momentum protocol: abort gates

Written 2026-11-15, before any run has produced a number. The protocol
requires the invested fraction to stay between 0.99 and 1.00 but does not say
where the run starts or what happens if too few names qualify. The agent brief
added rules the protocol did not contain. This file fixes them.

## Start of the run

Month-ends are skipped until the first one with at least 50 eligible names.
That month-end is the first rebalance. Skipped month-ends are listed in the
result.

## Gates (checked before any return statistic is computed)

The run aborts and writes no result if, at any rebalance from the first one on:
1. the invested fraction after fills, for basket or benchmark, is outside
   0.99 to 1.00; or
2. fewer than 50 names are eligible.

There is no grace period for either gate. On abort, the report states which
gate, the date and the value. Any further step needs a new amendment.

## Unchanged

Everything else in the protocol and Amendment 1.
