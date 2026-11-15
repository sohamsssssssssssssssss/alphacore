# Amendment 3 to the 12-1 momentum protocol: trades in names with missing inputs

Written 2026-11-15, before any run has produced a number. A synthetic test
showed the simulator has no rule for selling a held name whose 63-session
ADV window is no longer complete. This file fixes that case and the
neighbouring ones, so they are decided before the data is seen.

## Rules

1. **ADV for a trade in a held name.** If the name has no complete
   63-session point-in-time ADV on the rebalance day, the cost model uses its
   most recent earlier complete 63-session ADV. One always exists, because
   the name was eligible when bought. Each use is counted.
2. **Target with no open on the execution day (not held).** It is removed
   from the target set before sizing. The remaining targets share equity
   equally. Counted.
3. **Held name with no open on the execution day.** Carried at its most
   recent earlier close and not traded (Amendment 1). The remaining targets
   share the rest of equity equally. It is traded at the next rebalance on
   which it has an execution-day open: sold if no longer a target, resized
   if it is.
4. **Month-end with no later session.** Skipped; there is nothing to trade at.
5. **Invested fraction** for the gate in Amendment 2 counts carried holdings
   as invested.

## General principle for inputs

Where the documents are silent on an *input to a trade in a name already
held* (a price or an ADV), the most recent earlier point-in-time value is
used, never a later one, and the use is counted and listed in the result.
This principle does not extend to selection, eligibility, sizing targets,
costs parameters, the metric or the gates. A gap in any of those still stops
the run.

## Unchanged

Everything else in the protocol and Amendments 1 and 2.
