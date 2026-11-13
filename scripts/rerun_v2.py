#!/usr/bin/env python3.11
"""Replay locked experiments on verified data; write only research/v2."""
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from freeze_data import SNAPSHOT, verify
from engines.backtest_metrics import compute_sharpe, stationary_bootstrap_sharpe_ci
from experiments import cross_sectional_experiment as cross
from experiments import cross_sectional_diagnostic as fixed
from experiments import monthly_rebalance_test as monthly
from experiments import overnight_gap_experiment as gap
from experiments import universe_expansion_experiment as universe
from experiments import k_expansion_experiment as expansion
from experiments import basket_backtest as basket

OUT = ROOT / 'research/v2'
TEST_START = '2025-01-31'
RISK_FREE = .065
ZERO_RF = 'zero-rf'
EXCESS = 'excess (rf=0.065)'
EXPERIMENTS_DIR = ROOT / 'backend/experiments'


def code_line(filename, text, nth=0):
    """Quote the nth source line containing text, with its current line number."""
    lines = (EXPERIMENTS_DIR / filename).read_text().splitlines()
    hits = [i for i, line in enumerate(lines, 1) if text in line]
    if len(hits) <= nth:
        raise RuntimeError(f'Sizing line not found in {filename}: {text}')
    return f'backend/experiments/{filename}:{hits[nth]}: {lines[hits[nth] - 1].strip()}'


def long_short(filename, size):
    assert size == .10, 'deployed-fraction text assumes the locked 10% per leg'
    return {'summary': '10% long + 10% short of equity at entry (20% gross, ~0 net); rest idle cash earning 0',
            'kind': 'self-financing long/short overlay',
            'code': [code_line(filename, 'qty_l = (self.position_size_pct * equity)'),
                     code_line(filename, 'qty_s = (self.position_size_pct * equity)')]}


def old(filename):
    return json.loads((ROOT / 'research' / filename).read_text())


def daily(symbols, end):
    result = {}
    for symbol in symbols:
        path = SNAPSHOT / (symbol + '.csv')
        if not path.exists():
            raise RuntimeError(f'Missing frozen universe member: {symbol}')
        frame = pd.read_csv(path, parse_dates=['Date'])
        result[symbol] = frame.loc[frame.Date.between('2021-07-30', end)].reset_index(drop=True)
    return result


def held_out(panel):
    return panel.loc[panel.index >= pd.Timestamp(TEST_START)]


def consistent_metrics(returns, periods_per_year, n_bootstrap, mean_block_length, seed, risk_free=RISK_FREE):
    values = np.asarray(returns, dtype=float)
    if values.size < 2 or not np.isfinite(values).all():
        raise RuntimeError('Insufficient/nonfinite return series; no performance number invented')
    point = compute_sharpe(values.tolist(), periods_per_year=periods_per_year, risk_free=risk_free)
    ci = stationary_bootstrap_sharpe_ci(values, periods_per_year=periods_per_year, risk_free=risk_free,
                                       n_bootstrap=n_bootstrap, mean_block_length=mean_block_length, seed=seed)
    assert math.isclose(point, ci['sharpe'], rel_tol=1e-12, abs_tol=1e-12)
    return point, ci


def json_value(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def display(value):
    return 'not reported' if value is None else repr(value)


def ci_text(value):
    return 'not reported' if value is None else '[' + repr(value[0]) + ', ' + repr(value[1]) + ']'


def result_row(name, filename, result, baseline, parameters, bootstrap, *, deployed, primary=ZERO_RF, ppy=252, extra=None):
    returns = np.asarray(result['daily_returns'], dtype=float)
    # v2_sharpe/v2_ci keep their committed meaning (excess, rf=0.065); zero-rf is a parallel pair.
    point, ci = consistent_metrics(returns, ppy, *bootstrap)
    point0, ci0 = consistent_metrics(returns, ppy, *bootstrap, risk_free=0.0)
    primary_point, primary_ci = (point0, ci0) if primary == ZERO_RF else (point, ci)
    prior_point = baseline.get('sharpe')
    prior_ci = [baseline['ci_lower'], baseline['ci_upper']] if 'ci_lower' in baseline else None
    row = {'experiment': name, 'v1_sharpe': prior_point, 'v1_ci': prior_ci,
           'v2_sharpe': point, 'v2_ci': [ci['ci_lower'], ci['ci_upper']],
           'v2_sharpe_zero_rf': point0, 'v2_ci_zero_rf': [ci0['ci_lower'], ci0['ci_upper']],
           'primary_convention': primary, 'deployed_fraction': deployed,
           'primary_sharpe': primary_point,
           'primary_ci_excludes_zero': bool(primary_ci['ci_lower'] > 0 or primary_ci['ci_upper'] < 0),
           'primary_positive_ci': bool(primary_ci['ci_lower'] > 0),
           'sign_unchanged': None if prior_point is None else bool(np.sign(prior_point) == np.sign(point)),
           'ci_excludes_zero': bool(ci['ci_lower'] > 0 or ci['ci_upper'] < 0),
           'positive_ci': bool(ci['ci_lower'] > 0),
           'positive_ci_zero_rf': bool(ci0['ci_lower'] > 0),
           'nifty50_buy_hold_sharpe': None, 'equal_weight_buy_hold_sharpe': None,
           'nifty50_buy_hold_sharpe_zero_rf': None, 'equal_weight_buy_hold_sharpe_zero_rf': None}
    artifact = row | {'created_at': datetime.now(timezone.utc).isoformat(),
                     'manifest': 'data_snapshots/2026-11/MANIFEST.json',
                     'manifest_sha256': hashlib.sha256((SNAPSHOT / 'MANIFEST.json').read_bytes()).hexdigest(),
                     'parameters': parameters,
                     'metric_definition': {'annual_risk_free': RISK_FREE, 'zero_rf_annual_risk_free': 0.0,
                                           'periods_per_year': ppy, 'n_bootstrap': bootstrap[0],
                                           'mean_block_length': bootstrap[1], 'seed': bootstrap[2],
                                           'keys': 'v2_sharpe/v2_ci and consistent_bootstrap: excess, rf=0.065; '
                                                   '*_zero_rf: rf=0; ci_excludes_zero/positive_ci: excess; '
                                                   'primary_*: primary_convention'},
                     'returns': returns.tolist(), 'consistent_bootstrap': ci,
                     'consistent_bootstrap_zero_rf': ci0, 'raw_backtest': result}
    if extra:
        artifact.update(extra)
        for key in ['nifty50_buy_hold_sharpe', 'equal_weight_buy_hold_sharpe',
                    'nifty50_buy_hold_sharpe_zero_rf', 'equal_weight_buy_hold_sharpe_zero_rf']:
            row[key] = extra[key]
    (OUT / filename).write_text(json.dumps(artifact, indent=2, default=json_value, allow_nan=False) + '\n')
    return row


def benchmarks(result, closes, opens):
    dates = pd.DatetimeIndex([basket.execution_day(closes, rb) for rb, _, _ in result['baskets']])
    index = pd.read_csv(SNAPSHOT / 'NSEI.csv', parse_dates=['Date']).set_index('Date')['Open']
    index_values = index.reindex(dates)
    if index_values.isna().any():
        raise RuntimeError('Index open missing on a basket observation date; no substituted prices')
    stock_values = opens.reindex(dates)
    if stock_values.isna().any().any():
        raise RuntimeError('Stock open missing on a benchmark observation date')
    # Fixed initial equal weights: buy-and-hold, not periodic rebalancing.
    equity = stock_values.div(stock_values.iloc[0]).mean(axis=1)
    index_returns = index_values.pct_change().iloc[1:].to_numpy()
    equal_returns = equity.pct_change().iloc[1:].to_numpy()
    assert len(index_returns) == len(equal_returns) == len(result['period_returns'])
    return {'nifty50_buy_hold_sharpe': compute_sharpe(index_returns.tolist(), periods_per_year=12, risk_free=RISK_FREE),
            'equal_weight_buy_hold_sharpe': compute_sharpe(equal_returns.tolist(), periods_per_year=12, risk_free=RISK_FREE),
            'nifty50_buy_hold_sharpe_zero_rf': compute_sharpe(index_returns.tolist(), periods_per_year=12, risk_free=0.0),
            'equal_weight_buy_hold_sharpe_zero_rf': compute_sharpe(equal_returns.tolist(), periods_per_year=12, risk_free=0.0),
            'benchmark_returns': {'nifty50': index_returns.tolist(), 'equal_weight': equal_returns.tolist()},
            'benchmark_observation_dates': [str(x.date()) for x in dates],
            'benchmark_basis': 'Gross next-session-open buy-and-hold; no trading costs; ^NSEI is a price index. Descriptive only.'}


def main():
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError('Python 3.11 required')
    manifest = verify()
    OUT.mkdir(exist_ok=True)
    v1_hashes = {p: p.read_bytes() for p in (ROOT / 'research').glob('*') if p.is_file()}
    rows = []
    five = cross.SYMBOLS
    daily_five = daily(five, '2026-07-30')
    cross_panel = cross.build_panel(daily_five)
    locked = old('cross_sectional_results.json')['parameters']['selected_n']
    parameters = {'lookback_n': locked, 'k': cross.K, 'rebalance_interval': cross.REBALANCE_INTERVAL,
                  'position_size_pct': cross.POSITION_SIZE_PCT, 'initial_capital': cross.INITIAL_CAPITAL,
                  'data_start': '2021-07-30', 'data_end': '2026-07-30', 'test_start': TEST_START,
                  'selection': 'N=20 taken from committed v1 selection; no train/config search rerun'}
    result = cross.CrossSectionalBacktester(held_out(cross_panel), locked, cross.K,
                                           cross.REBALANCE_INTERVAL, cross.POSITION_SIZE_PCT, cross.INITIAL_CAPITAL).run()
    rows.append(result_row('3 Cross-sectional', 'experiment_3_cross_sectional.json', result,
                           old('cross_sectional_results.json')['test_results'], parameters,
                           (cross.N_BOOTSTRAP, cross.MEAN_BLOCK_LENGTH, cross.BOOTSTRAP_SEED),
                           deployed=long_short('cross_sectional_experiment.py', cross.POSITION_SIZE_PCT)))
    parameters4 = parameters | {'lookback_n': fixed.LOOKBACK_N, 'rebalance_interval': monthly.REBALANCE_MONTHLY}
    result = fixed.FixedCrossSectionalBacktester(held_out(fixed.build_panel(daily_five)),
                lookback_n=fixed.LOOKBACK_N, k=monthly.K, rebalance_interval=monthly.REBALANCE_MONTHLY,
                position_size_pct=monthly.POSITION_SIZE_PCT, initial_capital=monthly.INITIAL_CAPITAL).run()
    rows.append(result_row('4 Monthly', 'experiment_4_monthly.json', result,
                           old('cross_sectional_monthly_results.json')['results'], parameters4,
                           (monthly.N_BOOTSTRAP, monthly.MEAN_BLOCK_LENGTH, monthly.BOOTSTRAP_SEED),
                           deployed=long_short('cross_sectional_diagnostic.py', monthly.POSITION_SIZE_PCT)))
    panel = gap.build_panel(daily_five)
    result = gap.run_overnight_gap_strategy(held_out(panel), gap.INITIAL_CAPITAL)
    gap_params = {'gap_threshold': gap.GAP_THRESHOLD, 'initial_capital': gap.INITIAL_CAPITAL,
                  'position_size_pct': gap.POSITION_SIZE_PCT, 'test_start': TEST_START, 'data_end': '2026-07-30'}
    rows.append(result_row('5 Overnight gap', 'experiment_5_overnight_gap.json', result,
                           old('overnight_gap_results.json')['overnight_gap'], gap_params,
                           (gap.N_BOOTSTRAP, gap.MEAN_BLOCK_LENGTH, gap.BOOTSTRAP_SEED),
                           deployed={'summary': f'10% of equity per triggered symbol, one direction, open to close; '
                                                f'0-{len(gap.SYMBOLS) * 10}% gross, unhedged',
                                     'kind': 'directional, partially deployed; not a self-financing overlay',
                                     'code': [code_line('overnight_gap_experiment.py', 'qty = (POSITION_SIZE_PCT * equity)', 0)]}))
    earnings = {}
    for symbol in five:
        name = 'earnings_' + symbol + '.csv'
        if name in manifest['files']:
            frame = pd.read_csv(SNAPSHOT / name)
            frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop('Date'), utc=True))
            zone = manifest['files'][name]['timezone']
            if zone:
                frame.index = frame.index.tz_convert(zone)
            earnings[symbol] = frame
    if len(earnings) != len(five):
        raise RuntimeError('PEAD earnings snapshot incomplete; no event history manufactured')
    # Retain the original calendar cut despite revisions changing row counts.
    gap.TEST_START_INDEX = int(panel.index.searchsorted(pd.Timestamp(TEST_START)))
    result = gap.run_pead_strategy(panel, earnings, gap.INITIAL_CAPITAL)
    rows.append(result_row('6 PEAD', 'experiment_6_pead.json', result, {},
                           gap_params | {'surprise_threshold': gap.PEAD_SURPRISE_THRESHOLD,
                                         'hold_days': gap.PEAD_HOLD_DAYS,
                                         'return_basis': 'Unchanged per-event bid/ask return before explicit model fees; net PnL separately includes costs.'},
                           (gap.N_BOOTSTRAP, gap.MEAN_BLOCK_LENGTH, gap.BOOTSTRAP_SEED), ppy=252 // gap.PEAD_HOLD_DAYS,
                           deployed={'summary': f'10% of equity per qualifying earnings event, one direction, '
                                                f'held {gap.PEAD_HOLD_DAYS} sessions; unhedged',
                                     'kind': 'directional, partially deployed; not a self-financing overlay',
                                     'code': [code_line('overnight_gap_experiment.py', 'qty = (POSITION_SIZE_PCT * equity)', 1)]}))
    symbols = old('universe_expansion_results.json')['data']['nifty50_symbols']
    panel50 = universe.build_panel(daily(symbols, '2026-07-29'), symbols)
    panel5 = universe.build_panel(daily(five, '2026-07-29'), sorted(five))
    parameters7 = {'lookback_n': universe.LOOKBACK_N, 'k': universe.K,
                   'rebalance_interval': universe.REBALANCE_INTERVAL, 'position_size_pct': universe.POSITION_SIZE_PCT,
                   'initial_capital': universe.INITIAL_CAPITAL, 'test_start': TEST_START, 'data_end': '2026-07-29'}
    for label, current, members, baseline in [('5', panel5, sorted(five), 'results_5_symbol'),
                                               ('49', panel50, symbols, 'results_nifty50')]:
        result = universe.CrossSectionalBacktester(held_out(current), members, universe.LOOKBACK_N, universe.K,
                  universe.REBALANCE_INTERVAL, universe.POSITION_SIZE_PCT, universe.INITIAL_CAPITAL).run()
        rows.append(result_row('7 Universe ' + label, 'experiment_7_universe_' + label + '.json', result,
                               old('universe_expansion_results.json')[baseline], parameters7 | {'symbols': members},
                               (universe.N_BOOTSTRAP, universe.MEAN_BLOCK_LENGTH, universe.BOOTSTRAP_SEED),
                               deployed=long_short('universe_expansion_experiment.py', universe.POSITION_SIZE_PCT)))
    assert expansion.POSITION_SIZE_PCT == .10
    k_deployed = {'summary': '10% of equity per leg split equally across K names (20% gross, ~0 net); rest idle cash earning 0',
                  'kind': 'self-financing long/short overlay',
                  'code': [code_line('k_expansion_experiment.py', 'per_position_pct = self.position_size_pct / k'),
                           code_line('k_expansion_experiment.py', 'qty = (per_position_pct * equity) / ask'),
                           code_line('k_expansion_experiment.py', 'qty = (per_position_pct * equity) / bid')]}
    for k in expansion.K_VALUES:
        result = expansion.KExpansionBacktester(held_out(panel50), expansion.LOOKBACK_N, k,
                  expansion.REBALANCE_INTERVAL, expansion.POSITION_SIZE_PCT, expansion.INITIAL_CAPITAL).run()
        rows.append(result_row('8 K=' + str(k), 'experiment_8_k' + str(k) + '.json', result,
                               old('k_expansion_results.json')['results_by_k'][str(k)], parameters7 | {'k': k},
                               (expansion.N_BOOTSTRAP, expansion.MEAN_BLOCK_LENGTH, expansion.BOOTSTRAP_SEED),
                               deployed=k_deployed))
    frames = {s: pd.read_csv(SNAPSHOT / (s + '.csv'), parse_dates=['Date']).set_index('Date')
              for s in basket.UNIVERSE_49 if (s + '.csv') in manifest['files']}
    closes = pd.DataFrame({s: f['Close'].dropna() for s, f in frames.items()})
    opens = pd.DataFrame({s: f['Open'].dropna() for s, f in frames.items()})
    adv = {s: float((f['Close'] * f['Volume'].fillna(0)).tail(63).mean()) for s, f in frames.items()}
    schedule = basket.monthly_rebalance_dates(closes, date(2026, 8, 13))
    result = basket.simulate(closes, adv, opens, schedule)
    extra = benchmarks(result, closes, opens)
    result['daily_returns'] = result['period_returns']
    rows.append(result_row('K12 long-only basket', 'k12_basket.json', result,
                           {'sharpe': .6610, 'ci_lower': .5718, 'ci_upper': 1.9514},
                           {'k': result['k_used'], 'lookback': basket.LOOKBACK_TRADING_DAYS, 'frequency': 'monthly',
                            'budget': basket.DEFAULT_BUDGET_INR, 'spread_bps': basket.ASSUMED_SPREAD_BPS,
                            'data_start': '2020-08-14', 'data_end': '2026-08-13',
                            'v1_basis': 'Narrative quotation only; original raw result absent',
                            'cost_lookahead': 'Single ADV from final 63 sessions reused at every historical rebalance.'},
                           (1000, 10, 42), ppy=12, extra=extra, primary=EXCESS,
                           deployed={'summary': 'long-only, budget/k per name at entry (fully invested)',
                                     'kind': 'long-only, fully invested',
                                     'code': [code_line('basket_backtest.py', 'per_position = budget / max(len(basket), 1)')]}))
    unavailable = {'experiment': '9 Hourly', 'status': 'not reproducible: source data no longer obtainable',
                   'reason': 'Yahoo 730-day retention; no replacement window or synthetic bars used'}
    (OUT / 'experiment_9_hourly.json').write_text(json.dumps(unavailable, indent=2) + '\n')
    text = '# V2 frozen-data rerun — 2026-11-13\n\n'
    text += 'All strategy parameters/cost models are unchanged. Every Sharpe is shown under two conventions, each point with the CI from the same convention, bootstrap and seed: zero-rf (rf=0) and excess-return (annual rf=0.065). No training, N search or NSGA-II re-selection was run. Calendar split dates are retained even where revised row counts differ from v1 index 867.\n\n'
    text += '| experiment | deployed (from code) | primary | zero-rf Sharpe | zero-rf CI | excess Sharpe (rf=0.065) | excess CI (rf=0.065) | primary CI excludes zero? | v1 Sharpe | v1 CI |\n'
    text += '|---|---|---|---:|---|---:|---|---|---:|---|\n'
    for row in rows:
        text += (f"| {row['experiment']} | {row['deployed_fraction']['summary']} | {row['primary_convention']} "
                 f"| {display(row['v2_sharpe_zero_rf'])} | {ci_text(row['v2_ci_zero_rf'])} "
                 f"| {display(row['v2_sharpe'])} | {ci_text(row['v2_ci'])} "
                 f"| {'yes' if row['primary_ci_excludes_zero'] else 'no'} | {display(row['v1_sharpe'])} | {ci_text(row['v1_ci'])} |\n")
    hourly = old('intraday_signal_results.json')['results']
    text += '| 9 Hourly | not applicable | not applicable | not reproducible: source data no longer obtainable | not available | not reproducible | not available | not assessable | ' + str(hourly['sharpe']) + ' | ' + ci_text([hourly['ci_lower'], hourly['ci_upper']]) + ' |\n'
    k12 = next(row for row in rows if row['experiment'] == 'K12 long-only basket')
    text += '\nK12 benchmarks (gross price-based buy-and-hold at the basket observation dates, no CI):\n\n'
    text += '| series | zero-rf Sharpe | excess Sharpe (rf=0.065) |\n|---|---:|---:|\n'
    text += f"| K12 basket (net of modelled costs) | {display(k12['v2_sharpe_zero_rf'])} | {display(k12['v2_sharpe'])} |\n"
    text += f"| ^NSEI buy-and-hold | {display(k12['nifty50_buy_hold_sharpe_zero_rf'])} | {display(k12['nifty50_buy_hold_sharpe'])} |\n"
    text += f"| equal-weight buy-and-hold | {display(k12['equal_weight_buy_hold_sharpe_zero_rf'])} | {display(k12['equal_weight_buy_hold_sharpe'])} |\n"
    text += '\n## Which convention applies\n\n'
    text += '- **Experiments 3, 4, 7, 8 (long/short):** self-financing overlays with 20% of equity gross deployed (10% long, 10% short); the other ~80% is idle cash that earns nothing in these backtests. Subtracting rf from equity returns therefore charges the strategy for cash it never deploys. **Primary = zero-rf.** The excess-return column is shown as cash-drag-inclusive.\n'
    text += '- **Experiments 5, 6 (overnight gap, PEAD):** not long/short overlays. Each trade is one unhedged 10%-of-equity position, long or short; the rest is idle cash earning nothing, as above. **Primary = zero-rf**, for the same idle-cash reason. Excess-return is again cash-drag-inclusive.\n'
    text += '- **K12 basket:** long-only and fully invested, so its alternative is holding cash or the index. **Primary = excess-return (rf=0.065)**, compared with ^NSEI and equal-weight buy-and-hold under the same convention.\n'
    text += '- Neither convention prices short-borrow or margin financing. Sharpe values across rows with different deployment are not directly comparable.\n'
    text += '\n## Deployed fraction (quoted from code)\n\n'
    for row in rows:
        text += f"- **{row['experiment']}** ({row['deployed_fraction']['kind']}):\n"
        for quote in row['deployed_fraction']['code']:
            text += f'  - `{quote}`\n'
    text += '\n## Interpretation and limitations\n\n'
    text += '- K12 is long-only; its Sharpe is not comparable to the long/short experiments. Its known cost lookahead (one ADV from the final 63 sessions) is unchanged.\n'
    text += '- K12 v1 numbers are an unverified narrative quotation. V2 uses fresh frozen data, not recovered v1 inputs.\n'
    text += '- Benchmark columns are descriptive, gross, price-based buy-and-hold with no transaction costs, at the exact same next-session-open observation dates as the basket. Equal weights are fixed at inception across the available basket universe; they are not rebalanced.\n'
    text += '- PEAD retains the original per-event return definition before explicit model fees; its net PnL includes those fees separately. V1 PEAD point/CI was not recorded. Its newly frozen earnings calendar is not a recovered v1 event snapshot.\n'
    text += '- Experiment 3 retains its original backtester (including the historically documented MTM problem); experiment 4 uses its existing corrected backtester. No strategy bug was silently fixed.\n'
    text += '- Cross-sectional/universe/K/hourly v1 JSON points were often zero-rf points; see ../METRICS_ERRATUM.md. v1 columns are as recorded, not re-labelled.\n'
    text += '- Historical-window reuse, current-universe bias and selection bias remain; this is not fresh out-of-sample validation. Short borrow costs remain unmodeled, as in v1.\n'
    if any(row['primary_positive_ci'] for row in rows):
        text += '\n**HUMAN DECISION REQUIRED:** at least one primary-convention v2 CI excludes zero positively. The README headline has deliberately not been edited. This is not evidence that selection bias, cost lookahead or execution validation has been resolved.\n'
    else:
        text += '\nNo primary-convention v2 strategy CI excludes zero on the positive side.\n'
    others = [row['experiment'] for row in rows if (row['positive_ci'] or row['positive_ci_zero_rf']) and not row['primary_positive_ci']]
    if others:
        text += 'Under the non-primary convention, a positive CI occurs for: ' + ', '.join(others) + '.\n'
    (OUT / 'SUMMARY.md').write_text(text)
    assert all(p.read_bytes() == content for p, content in v1_hashes.items()), 'v1 research file changed'
    verify()
    print(text)


if __name__ == '__main__':
    main()
