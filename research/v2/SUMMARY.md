# V2 frozen-data rerun — 2026-11-13

All strategy parameters/cost models are unchanged; both point and CI use annual rf=0.065. No training, N search or NSGA-II re-selection was run. Calendar split dates are retained even where revised row counts differ from v1 index 867.

| experiment | v1 Sharpe | v1 CI | v2 Sharpe | v2 CI | sign unchanged? | CI excludes zero? | ^NSEI buy-and-hold Sharpe | equal-weight buy-and-hold Sharpe |
|---|---:|---|---:|---|---|---|---:|---:|
| 3 Cross-sectional | -4.36571733540333 | [-6.644070471874096, -2.129286738204723] | -5.7107138309851635 | [-7.726057855688889, -3.5452241028571563] | yes | yes | not reported | not reported |
| 4 Monthly | -4.58863888701789 | [-3.5125300274265023, -0.6951667592425609] | -4.163989634673355 | [-5.533771228970785, -2.922490201581712] | yes | yes | not reported | not reported |
| 5 Overnight gap | -6.795219292962517 | [-5.872562342769051, -3.524728707004727] | -6.807571251322499 | [-8.371809536936768, -5.600624730784859] | yes | yes | not reported | not reported |
| 6 PEAD | not reported | not reported | -0.2052606351633211 | [-1.9353722569766492, 1.1828173360360115] | not assessable | no | not reported | not reported |
| 7 Universe 5 | -2.196819040599928 | [-3.592393366184472, -0.7825711412036436] | -4.156262290073925 | [-5.57330791227776, -2.868649193344605] | yes | yes | not reported | not reported |
| 7 Universe 49 | -1.5695621937298496 | [-3.1371605270276364, 0.04812026448287231] | -3.7785951031419356 | [-5.172710614919728, -2.2318427709874316] | yes | yes | not reported | not reported |
| 8 K=1 | -1.5695621937298496 | [-3.1371605270276364, 0.04812026448287231] | -3.7785951031419356 | [-5.172710614919728, -2.2318427709874316] | yes | yes | not reported | not reported |
| 8 K=5 | -3.240688124958872 | [-4.436505597380993, -2.0913684021313936] | -5.284444470696279 | [-6.38478378003651, -4.198309385121038] | yes | yes | not reported | not reported |
| 8 K=10 | -3.708240977582449 | [-4.364579276337645, -3.0552380711965745] | -5.292754454823805 | [-5.922470427081626, -4.668966152257211] | yes | yes | not reported | not reported |
| K12 long-only basket | 0.661 | [0.5718, 1.9514] | 0.6575848803769175 | [-0.2336407666642999, 1.3619463317249594] | yes | no | 0.5815416254775335 | 1.0057136423907516 |
| 9 Hourly | -3.1047984043353845 | [-3.9495188075811103, -2.34658020430775] | not reproducible: source data no longer obtainable | not available | not assessable | not assessable | not applicable | not applicable |

## Interpretation and limitations

- K12 is long-only; its Sharpe is not comparable to the long/short experiments. Its known cost lookahead (one ADV from the final 63 sessions) is unchanged.
- K12 v1 numbers are an unverified narrative quotation. V2 uses fresh frozen data, not recovered v1 inputs.
- Benchmark columns are descriptive, gross, price-based buy-and-hold with no transaction costs, at the exact same next-session-open observation dates as the basket. Equal weights are fixed at inception across the available basket universe; they are not rebalanced.
- PEAD retains the original per-event return definition before explicit model fees; its net PnL includes those fees separately. V1 PEAD point/CI was not recorded. Its newly frozen earnings calendar is not a recovered v1 event snapshot.
- Experiment 3 retains its original backtester (including the historically documented MTM problem); experiment 4 uses its existing corrected backtester. No strategy bug was silently fixed.
- Cross-sectional/universe/K/hourly v1 JSON points were often zero-rf points; see ../METRICS_ERRATUM.md.
- Historical-window reuse, current-universe bias and selection bias remain; this is not fresh out-of-sample validation. Short borrow costs remain unmodeled, as in v1.

No v2 strategy CI excludes zero on the positive side.
