# Metrics erratum — 2026-11-13

`compute_sharpe` defaults to annual risk_free=0.065 and subtracts
`(1+risk_free)**(1/periods_per_year)-1` from each return. The v1 shared
stationary bootstrap used zero-rf returns in both its full-sample estimate
and every resample. Pairing an excess-return point with that zero-rf CI
compares different estimands. Some v1 points therefore lie outside their
quoted CIs. A confidence interval need not contain its sample point in every
dataset, so outside-CI placement alone is not the proof; the different code
definitions are the proof here.

The bootstrap now accepts risk_free, default **0.0**, preserving v1 behavior
bit-for-bit. V2 explicitly supplies **0.065** to both point and CI, retaining
the same seeds, resample counts, block lengths, annualization and strategies.
Existing reports/results are not rewritten. Correcting metric consistency
neither validates a strategy nor addresses data revisions or selection bias.

## Scope and exceptions

V1 shared-bootstrap CIs are zero-rf; points from compute_sharpe/full_metrics
are excess-return. The premise that *every published pair* differs is too
broad: cross-sectional, universe, K-expansion and hourly JSON writers often
stored ci["sharpe"], so those pairs are zero-rf/zero-rf. Their separately
computed excess point was not the stored point. The legacy NSGA-II real-data
driver uses a separate IID bootstrap calling compute_sharpe, so its point
and CI are both excess-return; it is not affected by this particular bug.
The synthetic weight report shows both definitions in different tables.

The table uses exact committed JSON values and identifies the branch/artifact;
report prose may round or disagree. For example, ALPHACORE_BACKTEST_REPORT's
headline is -11.3, whereas its linked JSON test Sharpe is the value below.
PEAD's v1 report/JSON does not record a point/CI pair. The K12 historical
quotation has no recovered raw result; it is included as an unverified claim.

## Erratum table

| Report / artifact | Branch | v1 point Sharpe | v1 CI | Point outside CI? | Point / CI definition |
|---|---|---:|---|---|---|
| [CROSS_SECTIONAL_EXPERIMENT_REPORT.md](cross_sectional_results.json) | test | -4.36571733540333 | [-6.644070471874096, -2.129286738204723] | no | zero-rf / zero-rf |
| [cross_sectional_diagnostic_results.json](cross_sectional_diagnostic_results.json) | corrected | -7.1922211691108835 | [-6.992296847225346, -3.980072587327611] | yes | excess / zero-rf |
| [CROSS_SECTIONAL_MONTHLY_REPORT.md](cross_sectional_monthly_results.json) | monthly | -4.58863888701789 | [-3.5125300274265023, -0.6951667592425609] | yes | excess / zero-rf |
| [OVERNIGHT_GAP_EXPERIMENT_REPORT.md](overnight_gap_results.json) | gap | -6.795219292962517 | [-5.872562342769051, -3.524728707004727] | yes | excess / zero-rf |
| [OVERNIGHT_GAP_EXPERIMENT_REPORT.md](overnight_gap_results.json) | PEAD | not reported | not reported | not reported | excess / zero-rf |
| [UNIVERSE_EXPANSION_EXPERIMENT_REPORT.md](universe_expansion_results.json) | results_5_symbol | -2.196819040599928 | [-3.592393366184472, -0.7825711412036436] | no | zero-rf / zero-rf |
| [UNIVERSE_EXPANSION_EXPERIMENT_REPORT.md](universe_expansion_results.json) | results_nifty50 | -1.5695621937298496 | [-3.1371605270276364, 0.04812026448287231] | no | zero-rf / zero-rf |
| [K_EXPANSION_EXPERIMENT_REPORT.md](k_expansion_results.json) | K=1 | -1.5695621937298496 | [-3.1371605270276364, 0.04812026448287231] | no | zero-rf / zero-rf |
| [K_EXPANSION_EXPERIMENT_REPORT.md](k_expansion_results.json) | K=5 | -3.240688124958872 | [-4.436505597380993, -2.0913684021313936] | no | zero-rf / zero-rf |
| [K_EXPANSION_EXPERIMENT_REPORT.md](k_expansion_results.json) | K=10 | -3.708240977582449 | [-4.364579276337645, -3.0552380711965745] | no | zero-rf / zero-rf |
| [INTRADAY_SIGNAL_EXPERIMENT_REPORT.md](intraday_signal_results.json) | hourly | -3.1047984043353845 | [-3.9495188075811103, -2.34658020430775] | no | zero-rf / zero-rf |
| [SIGNAL_WEIGHT_EXPERIMENT_REPORT.md](weight_comparison_results.json) | arm_a metrics table | -2.055121007444906 | [-2.810887816191746, 1.16702728678454] | no | excess / zero-rf |
| [SIGNAL_WEIGHT_EXPERIMENT_REPORT.md](weight_comparison_results.json) | arm_a CI table | -0.6949431353619917 | [-2.810887816191746, 1.16702728678454] | no | zero-rf / zero-rf |
| [SIGNAL_WEIGHT_EXPERIMENT_REPORT.md](weight_comparison_results.json) | arm_b metrics table | -1.996927387300785 | [-2.7701773491140047, 1.294789295218916] | no | excess / zero-rf |
| [SIGNAL_WEIGHT_EXPERIMENT_REPORT.md](weight_comparison_results.json) | arm_b CI table | -0.6304954782416207 | [-2.7701773491140047, 1.294789295218916] | no | zero-rf / zero-rf |
| [REAL_DATA_EXPERIMENT_REPORT.md](EXPERIMENT_RESULTS.json) | RELIANCE arm_a legacy | -10.58 | [-11.59, -1.03] | no | excess / excess (custom IID bootstrap) |
| [REAL_DATA_EXPERIMENT_REPORT.md](EXPERIMENT_RESULTS.json) | RELIANCE arm_b legacy | -10.66 | [-11.46, -1.1] | no | excess / excess (custom IID bootstrap) |
| [REAL_DATA_EXPERIMENT_REPORT.md](EXPERIMENT_RESULTS.json) | TCS arm_a legacy | 0.0 | [0.0, 0.0] | no | excess / excess (custom IID bootstrap) |
| [REAL_DATA_EXPERIMENT_REPORT.md](EXPERIMENT_RESULTS.json) | TCS arm_b legacy | -5.59 | [-6.27, 2.33] | no | excess / excess (custom IID bootstrap) |
| [REAL_DATA_EXPERIMENT_REPORT.md](EXPERIMENT_RESULTS.json) | INFY arm_a legacy | -6.43 | [-9.37, 2.26] | no | excess / excess (custom IID bootstrap) |
| [REAL_DATA_EXPERIMENT_REPORT.md](EXPERIMENT_RESULTS.json) | INFY arm_b legacy | -7.55 | [-9.32, 0.41] | no | excess / excess (custom IID bootstrap) |
| [REAL_DATA_EXPERIMENT_REPORT.md](EXPERIMENT_RESULTS.json) | HDFCBANK arm_a legacy | -8.7 | [-10.83, 0.81] | no | excess / excess (custom IID bootstrap) |
| [REAL_DATA_EXPERIMENT_REPORT.md](EXPERIMENT_RESULTS.json) | HDFCBANK arm_b legacy | -9.62 | [-11.01, -0.53] | no | excess / excess (custom IID bootstrap) |
| [REAL_DATA_EXPERIMENT_REPORT.md](EXPERIMENT_RESULTS.json) | ICICIBANK arm_a legacy | -7.59 | [-20.78, 5.2] | no | excess / excess (custom IID bootstrap) |
| [REAL_DATA_EXPERIMENT_REPORT.md](EXPERIMENT_RESULTS.json) | ICICIBANK arm_b legacy | -9.93 | [-10.4, 0.0] | no | excess / excess (custom IID bootstrap) |
| [REAL_DATA_EXPERIMENT_REPORT.md](../backend/real_data_results.json) | RELIANCE arm_a validation | -10.585236013681827 | [-16.12172323618148, -4.548152429893654] | no | excess / zero-rf |
| [REAL_DATA_EXPERIMENT_REPORT.md](../backend/real_data_results.json) | RELIANCE arm_b validation | -10.669590998329516 | [-16.206702746326187, -4.672214005332623] | no | excess / zero-rf |
| [REAL_DATA_EXPERIMENT_REPORT.md](../backend/real_data_results.json) | TCS arm_a validation | -5.58249538105307 | [-9.32840205997956, -1.1752877389880751] | no | excess / zero-rf |
| [REAL_DATA_EXPERIMENT_REPORT.md](../backend/real_data_results.json) | TCS arm_b validation | -5.58249538105307 | [-9.32840205997956, -1.1752877389880751] | no | excess / zero-rf |
| [REAL_DATA_EXPERIMENT_REPORT.md](../backend/real_data_results.json) | INFY arm_a validation | -7.542007157075434 | [-13.475303419193354, -2.4426855845154383] | no | excess / zero-rf |
| [REAL_DATA_EXPERIMENT_REPORT.md](../backend/real_data_results.json) | INFY arm_b validation | -7.542007157075434 | [-13.475303419193354, -2.4426855845154383] | no | excess / zero-rf |
| [REAL_DATA_EXPERIMENT_REPORT.md](../backend/real_data_results.json) | HDFCBANK arm_a validation | -9.62194213387594 | [-14.946707081230489, -4.52695852135695] | no | excess / zero-rf |
| [REAL_DATA_EXPERIMENT_REPORT.md](../backend/real_data_results.json) | HDFCBANK arm_b validation | -9.62194213387594 | [-14.946707081230489, -4.52695852135695] | no | excess / zero-rf |
| [REAL_DATA_EXPERIMENT_REPORT.md](../backend/real_data_results.json) | ICICIBANK arm_a validation | -9.923976422623712 | [-16.98792204424028, -3.9920554703844555] | no | excess / zero-rf |
| [REAL_DATA_EXPERIMENT_REPORT.md](../backend/real_data_results.json) | ICICIBANK arm_b validation | -9.923976422623712 | [-16.98792204424028, -3.9920554703844555] | no | excess / zero-rf |
| [ALPHACORE_BACKTEST_REPORT.md](backtest_results.json) | linked JSON | -11.147542901871363 | not reported | not reported | excess / zero-rf |
| [K12_BASKET_HYPOTHESIS.md](K12_BASKET_HYPOTHESIS.md) | historical quotation (raw missing) | 0.661 | [0.5718, 1.9514] | no | excess / zero-rf; unverified quote |
| [K12_BASKET_PROVENANCE.md](K12_BASKET_PROVENANCE.md) | Phase 2 fresh run | 0.6575851555529214 | [0.5708059735482527, 1.9477991082373192] | no | excess / zero-rf |

Each row identifies a frozen v1 artifact, not a recomputed v1 claim. V2 results and raw returns are in `research/v2/`; missing original data prevents exact historical reconstruction. No NSGA-II driver was rerun.
