# V2 frozen-data rerun — 2026-11-13

All strategy parameters/cost models are unchanged. Every Sharpe is shown under two conventions, each point with the CI from the same convention, bootstrap and seed: zero-rf (rf=0) and excess-return (annual rf=0.065). No training, N search or NSGA-II re-selection was run. Calendar split dates are retained even where revised row counts differ from v1 index 867.

| experiment | deployed (from code) | primary | zero-rf Sharpe | zero-rf CI | excess Sharpe (rf=0.065) | excess CI (rf=0.065) | primary CI excludes zero? | v1 Sharpe | v1 CI |
|---|---|---|---:|---|---:|---|---|---:|---|
| 3 Cross-sectional | 10% long + 10% short of equity at entry (20% gross, ~0 net); rest idle cash earning 0 | zero-rf | -4.897412860550125 | [-6.945383216175387, -2.6874719367724342] | -5.7107138309851635 | [-7.726057855688889, -3.5452241028571563] | yes | -4.36571733540333 | [-6.644070471874096, -2.129286738204723] |
| 4 Monthly | 10% long + 10% short of equity at entry (20% gross, ~0 net); rest idle cash earning 0 | zero-rf | -1.7202372520348328 | [-2.9597082999473567, -0.43327325494850083] | -4.163989634673355 | [-5.533771228970785, -2.922490201581712] | yes | -4.58863888701789 | [-3.5125300274265023, -0.6951667592425609] |
| 5 Overnight gap | 10% of equity per triggered symbol, one direction, open to close; 0-50% gross, unhedged | zero-rf | -4.642652453651895 | [-5.886271101573066, -3.5013558823516884] | -6.807571251322499 | [-8.371809536936768, -5.600624730784859] | yes | -6.795219292962517 | [-5.872562342769051, -3.524728707004727] |
| 6 PEAD | 10% of equity per qualifying earnings event, one direction, held 10 sessions; unhedged | zero-rf | 0.023492474053736955 | [-1.659985448840465, 1.4136557449310676] | -0.2052606351633211 | [-1.9353722569766492, 1.1828173360360115] | no | not reported | not reported |
| 7 Universe 5 | 10% long + 10% short of equity at entry (20% gross, ~0 net); rest idle cash earning 0 | zero-rf | -1.7160082242155525 | [-3.0048822601799117, -0.3391287402187751] | -4.156262290073925 | [-5.57330791227776, -2.868649193344605] | yes | -2.196819040599928 | [-3.592393366184472, -0.7825711412036436] |
| 7 Universe 49 | 10% long + 10% short of equity at entry (20% gross, ~0 net); rest idle cash earning 0 | zero-rf | -1.9426672674071759 | [-3.3210896840840416, -0.33916023789201966] | -3.7785951031419356 | [-5.172710614919728, -2.2318427709874316] | yes | -1.5695621937298496 | [-3.1371605270276364, 0.04812026448287231] |
| 8 K=1 | 10% of equity per leg split equally across K names (20% gross, ~0 net); rest idle cash earning 0 | zero-rf | -1.9426672674071759 | [-3.3210896840840416, -0.33916023789201966] | -3.7785951031419356 | [-5.172710614919728, -2.2318427709874316] | yes | -1.5695621937298496 | [-3.1371605270276364, 0.04812026448287231] |
| 8 K=5 | 10% of equity per leg split equally across K names (20% gross, ~0 net); rest idle cash earning 0 | zero-rf | -3.050178739887899 | [-4.127592894507842, -1.9531085119179696] | -5.284444470696279 | [-6.38478378003651, -4.198309385121038] | yes | -3.240688124958872 | [-4.436505597380993, -2.0913684021313936] |
| 8 K=10 | 10% of equity per leg split equally across K names (20% gross, ~0 net); rest idle cash earning 0 | zero-rf | -3.703727572379881 | [-4.332889610907947, -3.0662159469423584] | -5.292754454823805 | [-5.922470427081626, -4.668966152257211] | yes | -3.708240977582449 | [-4.364579276337645, -3.0552380711965745] |
| K12 long-only basket | long-only, budget/k per name at entry (fully invested) | excess (rf=0.065) | 1.2348124858145786 | [0.5708058892978265, 1.9477988180186856] | 0.6575848803769175 | [-0.2336407666642999, 1.3619463317249594] | no | 0.661 | [0.5718, 1.9514] |
| 9 Hourly | not applicable | not applicable | not reproducible: source data no longer obtainable | not available | not reproducible | not available | not assessable | -3.1047984043353845 | [-3.9495188075811103, -2.34658020430775] |

K12 benchmarks (gross price-based buy-and-hold at the basket observation dates, no CI):

| series | zero-rf Sharpe | excess Sharpe (rf=0.065) |
|---|---:|---:|
| K12 basket (net of modelled costs) | 1.2348124858145786 | 0.6575848803769175 |
| ^NSEI buy-and-hold | 1.047285435316514 | 0.5815416254775335 |
| equal-weight buy-and-hold | 1.404694863918583 | 1.0057136423907516 |

## Which convention applies

- **Experiments 3, 4, 7, 8 (long/short):** self-financing overlays with 20% of equity gross deployed (10% long, 10% short); the other ~80% is idle cash that earns nothing in these backtests. Subtracting rf from equity returns therefore charges the strategy for cash it never deploys. **Primary = zero-rf.** The excess-return column is shown as cash-drag-inclusive.
- **Experiments 5, 6 (overnight gap, PEAD):** not long/short overlays. Each trade is one unhedged 10%-of-equity position, long or short; the rest is idle cash earning nothing, as above. **Primary = zero-rf**, for the same idle-cash reason. Excess-return is again cash-drag-inclusive.
- **K12 basket:** long-only and fully invested, so its alternative is holding cash or the index. **Primary = excess-return (rf=0.065)**, compared with ^NSEI and equal-weight buy-and-hold under the same convention.
- Neither convention prices short-borrow or margin financing. Sharpe values across rows with different deployment are not directly comparable.

## Deployed fraction (quoted from code)

- **3 Cross-sectional** (self-financing long/short overlay):
  - `backend/experiments/cross_sectional_experiment.py:270: qty_l = (self.position_size_pct * equity) / ask if ask > 0 else 0.0`
  - `backend/experiments/cross_sectional_experiment.py:292: qty_s = (self.position_size_pct * equity) / bid if bid > 0 else 0.0`
- **4 Monthly** (self-financing long/short overlay):
  - `backend/experiments/cross_sectional_diagnostic.py:307: qty_l = (self.position_size_pct * equity) / ask if ask > 0 else 0.0`
  - `backend/experiments/cross_sectional_diagnostic.py:336: qty_s = (self.position_size_pct * equity) / bid if bid > 0 else 0.0`
- **5 Overnight gap** (directional, partially deployed; not a self-financing overlay):
  - `backend/experiments/overnight_gap_experiment.py:147: qty = (POSITION_SIZE_PCT * equity) / entry_price if entry_price > 0 else 0.0`
- **6 PEAD** (directional, partially deployed; not a self-financing overlay):
  - `backend/experiments/overnight_gap_experiment.py:295: qty = (POSITION_SIZE_PCT * equity) / entry_price if entry_price > 0 else 0.0`
- **7 Universe 5** (self-financing long/short overlay):
  - `backend/experiments/universe_expansion_experiment.py:276: qty_l = (self.position_size_pct * equity) / ask if ask > 0 else 0.0`
  - `backend/experiments/universe_expansion_experiment.py:299: qty_s = (self.position_size_pct * equity) / bid if bid > 0 else 0.0`
- **7 Universe 49** (self-financing long/short overlay):
  - `backend/experiments/universe_expansion_experiment.py:276: qty_l = (self.position_size_pct * equity) / ask if ask > 0 else 0.0`
  - `backend/experiments/universe_expansion_experiment.py:299: qty_s = (self.position_size_pct * equity) / bid if bid > 0 else 0.0`
- **8 K=1** (self-financing long/short overlay):
  - `backend/experiments/k_expansion_experiment.py:96: per_position_pct = self.position_size_pct / k`
  - `backend/experiments/k_expansion_experiment.py:248: qty = (per_position_pct * equity) / ask if ask > 0 else 0.0`
  - `backend/experiments/k_expansion_experiment.py:273: qty = (per_position_pct * equity) / bid if bid > 0 else 0.0`
- **8 K=5** (self-financing long/short overlay):
  - `backend/experiments/k_expansion_experiment.py:96: per_position_pct = self.position_size_pct / k`
  - `backend/experiments/k_expansion_experiment.py:248: qty = (per_position_pct * equity) / ask if ask > 0 else 0.0`
  - `backend/experiments/k_expansion_experiment.py:273: qty = (per_position_pct * equity) / bid if bid > 0 else 0.0`
- **8 K=10** (self-financing long/short overlay):
  - `backend/experiments/k_expansion_experiment.py:96: per_position_pct = self.position_size_pct / k`
  - `backend/experiments/k_expansion_experiment.py:248: qty = (per_position_pct * equity) / ask if ask > 0 else 0.0`
  - `backend/experiments/k_expansion_experiment.py:273: qty = (per_position_pct * equity) / bid if bid > 0 else 0.0`
- **K12 long-only basket** (long-only, fully invested):
  - `backend/experiments/basket_backtest.py:214: per_position = budget / max(len(basket), 1)`

## Interpretation and limitations

- K12 is long-only; its Sharpe is not comparable to the long/short experiments. Its known cost lookahead (one ADV from the final 63 sessions) is unchanged.
- K12 v1 numbers are an unverified narrative quotation. V2 uses fresh frozen data, not recovered v1 inputs.
- Benchmark columns are descriptive, gross, price-based buy-and-hold with no transaction costs, at the exact same next-session-open observation dates as the basket. Equal weights are fixed at inception across the available basket universe; they are not rebalanced.
- PEAD retains the original per-event return definition before explicit model fees; its net PnL includes those fees separately. V1 PEAD point/CI was not recorded. Its newly frozen earnings calendar is not a recovered v1 event snapshot.
- Experiment 3 retains its original backtester (including the historically documented MTM problem); experiment 4 uses its existing corrected backtester. No strategy bug was silently fixed.
- Cross-sectional/universe/K/hourly v1 JSON points were often zero-rf points; see ../METRICS_ERRATUM.md. v1 columns are as recorded, not re-labelled.
- Historical-window reuse, current-universe bias and selection bias remain; this is not fresh out-of-sample validation. Short borrow costs remain unmodeled, as in v1.

No primary-convention v2 strategy CI excludes zero on the positive side.
Under the non-primary convention, a positive CI occurs for: K12 long-only basket.
