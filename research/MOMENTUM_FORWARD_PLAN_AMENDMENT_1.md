# Amendment 1 to the momentum forward plan: late months and month-end

Written 2026-11-15, before the tool exists and before any forward month.

## Which return a late log excludes

A log chooses the holdings for the holding period that starts at its
execution session. If that log is late (or has no receipt), the return of
**that** holding period is excluded, for basket, benchmark and active alike,
and the month is reported as missed. The return of the period that ended at
that execution is unaffected.

The paper accounts still trade on a late month, using the late log, so the
account state stays continuous. Only the record excludes the period.

## End of test and the final figure

The test ends with the rebalance at the last session of November 2028,
whatever the number of missed months. It is not extended.

The 24-month IR uses the on-time holding periods only, and the number missed
is stated beside it. With fewer than 18 on-time periods no IR is reported,
only the monthly table.

## Establishing month-end before later sessions exist

`research/momentum/forward/nse_holidays.txt` lists NSE equity trading
holidays (one ISO date per line, from NSE's published list, with the source
noted). It is tracked, and any edit is a visible commit. An unscheduled
closure is added with a note when it happens.

A log for date D is accepted only if all hold:
1. D is the newest session in the fetched data;
2. every Monday-to-Friday date after D in the same calendar month is in the
   holiday file (or there is none);
3. the log runs at or after 15:30 IST on D.

The execution session is the first Monday-to-Friday date after D that is not
in the holiday file. A log is on time if its receipt is stamped before 09:15
IST on that date.

If the holiday file has no entries for D's year, the log is refused.
