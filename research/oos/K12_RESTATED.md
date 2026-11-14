in-sample, descriptive

# K=12 NSE basket, restated under Amendment 1

The data were used to choose this basket. These figures are descriptive only and are not evidence of an edge. Raw output: `research/oos/k12_restated.json`. The legacy figures in `research/v2/k12_basket.json` are unchanged and were not recomputed.

**Setup.** 21-session lookback, k = n_ranked // 4, monthly, next-session open. Point-in-time ADV, `CostModel()` defaults with brokerage kept (a real NSE fee), spread 10 bps, budget 1,000,000. The basket and an equal-weight benchmark (k = all eligible) both use `simulate_rebalanced`. Data are the frozen `data_snapshots/2026-11` CSVs through 2026-08-13. 48 of 49 symbols are used; TATAMOTORS has no CSV in the snapshot and is dropped, as in the original fetch.

**Window.** 73 scheduled month-ends (2020-08-31 to 2026-08-13, the data cutoff) with 68 monthly periods. The first actionable rebalance is 2020-11-27, because a full 63-session ADV window is needed. The legacy file has 70 periods.

## Sharpe under both conventions

Each CI uses the existing K12 file's bootstrap settings: 1000 resamples, mean block 10, seed 42, 95%.

| | Basket | Equal-weight benchmark |
|---|---|---|
| Sharpe, zero rf | 1.0522 | 1.3877 |
| 95% CI, zero rf | [0.2580, 1.9084] | [0.7260, 2.1852] |
| Sharpe, rf 0.065 | 0.5867 | 0.9232 |
| 95% CI, rf 0.065 | [-0.2240, 1.4310] | [0.2580, 1.6880] |

## Active return (T2 settings)

Monthly active return = basket net minus benchmark net. IR = mean / std × √12, rf 0. Stationary bootstrap, 2000 resamples, block 3, seed 2026, 95%.

- Active IR: -0.6088
- 95% CI: [-1.3654, 0.1585]

## Exposure, costs and turnover

| | Basket | Benchmark |
|---|---|---|
| Invested fraction, min / mean / max | 0.994989 / 0.994991 / 0.994996 | 0.994993 / 0.994997 / 0.994998 |
| Total modelled costs (INR) | 206,616.98 | 73,161.99 |
| Average turnover after entry (traded notional / equity) | 1.4968 | 0.0487 |
| Final equity (INR) | 2,121,269.36 | 2,741,317.20 |

## Legacy figures, for reference only

From `research/v2/k12_basket.json`, not recomputed: zero-rf Sharpe 1.2348 with CI [0.5708, 1.9478]. rf 0.065 Sharpe 0.6576 with CI [-0.2336, 1.3619]. Equal-weight buy-and-hold zero-rf Sharpe 1.4047.
