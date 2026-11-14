# Amendment 1 to the 12-1 momentum protocol: market calendar

Written 2026-11-14 after the first run attempt crashed before producing any
return, eligibility count or result file. No performance number from this
data has been seen. The universe (453 tickers, 451 with data) and the frozen
snapshot are unchanged.

## Gap

The protocol's eligibility rule and signal count "sessions of the market
calendar" but the repository defines no calendar. The frozen data's union of
dates contains rows that are not ordinary sessions (Saturdays with 1 to 10
names) and a few weekend special sessions with partial coverage.

## Rule (fixed here, before any run)

A date is a **session** if and only if both hold:
1. it is a Monday to Friday, and
2. at least half of the names *listed* on that date have a close, where a
   name is listed from the first to the last date with a close in its own
   frozen file, inclusive.

All rows on non-session dates are dropped before anything else is computed.
The signal lags (21 and 252), the 253-session completeness window, the
63-session ADV window, month-end rebalance dates and next-session execution
all count sessions on this calendar.

Weekend special sessions (for example Diwali evening trading) are excluded by
part 1. They are few, short, and unevenly covered by the data provider;
keeping them would make a name ineligible for a year for lacking one row.

## Held name with no price on an execution day

Valued at its most recent earlier close and not traded that day, as in the
corrected simulator. The lookup must skip missing values. Each occurrence is
counted in the result file.

## Unchanged

Everything else in the protocol, including eligibility rule 1 as written
(a close on every one of the last 253 sessions), the abort gates, the metric,
the decision table and the prediction.

## Recorded in the result

The session count, the list of dropped dates with their name counts, and the
crash and its fix.
