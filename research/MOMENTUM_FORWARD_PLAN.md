# 12-1 momentum: forward paper test plan

Written 2026-11-15, after the Candidate result
(`research/momentum/RESULT.md`) and before any forward month exists. It
carries out the "If Candidate" clause of `MOMENTUM_12_1_PROTOCOL.md`.
No real money is involved.

## What is fixed

- Strategy, eligibility, calendar rule, costs and simulator step: exactly as
  in the protocol and Amendments 1 to 3. Spread 30 bps, no flat brokerage.
- Universe: the frozen list `data_snapshots/nse500-2026-11/universe.txt`,
  unchanged for the whole test. Names that later leave the index stay in.
  This is what removes survivorship going forward.
- Two paper accounts of 10,000,000 INR: basket (top fifth) and benchmark
  (all eligible), both started at the first rebalance.
- First rebalance: last NSE session of November 2026. 24 monthly returns,
  ending with the rebalance at the last session of November 2028.

## Monthly procedure

1. **Log.** After the month's last session closes and before the next session
   opens, fetch daily bars for the universe, compute eligibility, signal and
   targets, and write `research/momentum/forward/YYYY-MM.json` (targets for
   both accounts, eligible names, signal values, input hashes, fetch time).
   Commit and push. The push time is the evidence that the basket was chosen
   before it traded.
2. **Mark.** After the next session, fill both accounts at that session's
   open with the cost model, update the state file, and record the previous
   month's net returns. Commit and push.

Rules:
- A log pushed after the next session's open is recorded as **late** and that
  month is excluded from the basket's record and reported as missed. No
  back-filling.
- Existing month files are never overwritten.
- Data for each month is whatever the provider returns on the log day; the
  bars used are hashed and the hash stored. Later revisions are not applied.
- A held name with no price is carried at its last close (Amendment 3). If it
  never trades again it stays at that value; each case is listed.

## Reporting

- Each month: a table of basket, benchmark and active net return, costs,
  turnover, invested fraction, eligible count. Descriptive only.
- No significance claim before 24 months.
- At 24 months: IR of monthly active returns with the protocol's bootstrap
  settings. Stated in advance: 24 observations give an interval half-width
  near 1.4 in IR, so this cannot confirm an edge of ordinary size. Wording:
  **consistent with the backtest** if the IR point estimate is above zero,
  **not consistent** otherwise. Either way the historical result remains a
  candidate, not a proven edge.

## Prediction

Forward IR point estimate above zero: 60%. Forward IR above the backtest's
1.01: 15%. The backtest is expected to overstate the edge because of
survivorship.

## Related decisions

- The forward log for the retired one-month basket (Arm B of
  `OOS_BASKET_PROTOCOL.md`) is discontinued. That basket showed no edge and
  nothing would be learned from tracking it.
- A historical test free of survivorship needs point-in-time index membership
  and prices for delisted stocks. If a source is found, it gets its own
  protocol.
