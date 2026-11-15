# Momentum forward paper test

No real money. Run from `backend/`, on an up-to-date `main` after this tool is merged.
The fixed test starts November 2026 and ends with the November 2028 rebalance.

After the final NSE session closes (at or after 15:30 IST), before the next session opens:
```sh
python3.11 -m experiments.momentum_forward log --as-of 2026-11-30
```
The command commits/pushes the month log and snapshot manifest, confirms it on GitHub,
and commits/pushes a publication receipt. It never overwrites a month log.
If publication fails, retry `python3.11 -m experiments.momentum_forward log --publish 2026-11`.

After that next session closes (at or after 15:30 IST):
```sh
python3.11 -m experiments.momentum_forward mark --month 2026-11
```
Change the date/month for each subsequent rebalance. Review, commit and push `state.json`.
Run `python3.11 -m experiments.momentum_forward report` to rebuild the monthly table.
A second mark of the same month is a no-op.

Late means no valid receipt, a remote log mismatch, or receipt time at/after execution-day
09:15 IST. Accounts still trade; the holding period starting then is missed for both
accounts and active returns. The preceding period is unaffected. Commit time is not used.

Only 2026 holidays are supplied. Before each new year's first log, add that year's
published NSE equity holiday circular dates to `nse_holidays.txt` in a separate commit.
Keep the gitignored `data_snapshots/momentum-forward/` payloads; marking checks their hashes.
