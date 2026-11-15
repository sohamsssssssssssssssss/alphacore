"""Registered momentum forward paper accounts; nothing runs on import."""
from __future__ import annotations

import argparse
import base64
import calendar
import hashlib
import io
import json
import re
import subprocess
import sys
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / 'experiments'))
from basket_backtest import _carry_px, _open_px, _rebalance_step
from momentum_12_1 import make_selectors, signal
from momentum_runner import (BUDGET, SPREAD_BPS, GATE_MIN_ELIGIBLE, sessions,
                             read_universe, stationary_bootstrap_sharpe_ci)
from engines.cost_model import CostModel
from prices import point_in_time_adv

FORWARD = ROOT / 'research/momentum/forward'
SNAPSHOTS = ROOT / 'data_snapshots/momentum-forward'
UNIVERSE = ROOT / 'data_snapshots/nse500-2026-11/universe.txt'
IST = ZoneInfo('Asia/Kolkata')
FIRST, LAST = '2026-11', '2028-11'
FIELDS = ('Open', 'High', 'Low', 'Close', 'Volume')


def utcnow():
    return datetime.now(timezone.utc)


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def read(path):
    return json.loads(path.read_text())


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def atomic(path, payload):
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('xb') as f:
        f.write(payload)
    tmp.replace(path)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def month_name(value):
    if not re.fullmatch(r'\d{4}-\d{2}', value):
        raise ValueError('month must be YYYY-MM')
    date.fromisoformat(value + '-01')
    if not FIRST <= value <= LAST:
        raise ValueError(f'forward months must be {FIRST} through {LAST}')
    return value


def next_month(value):
    d = date.fromisoformat(value + '-01')
    return (d.replace(day=28) + timedelta(days=4)).strftime('%Y-%m')


def fetch_bars(as_of, tickers):
    """One .NS request per name; no symbol substitution, and no truncation at as_of."""
    frames, unavailable = {}, {}
    for ticker in tickers:
        try:
            df = yf.download(ticker + '.NS', start=(as_of - timedelta(days=420)).isoformat(),
                             end=(utcnow().astimezone(IST).date() + timedelta(days=1)).isoformat(),
                             interval='1d', auto_adjust=True, progress=False, threads=False)
            if df is None or df.empty:
                raise ValueError('no daily data')
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.loc[:, list(FIELDS)].astype(float)
            df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
            if not df.index.is_unique or df['Close'].dropna().empty:
                raise ValueError('duplicate dates or no closes')
            frames[ticker] = df
        except Exception as exc:
            unavailable[ticker] = str(exc)
    if not frames:
        raise ValueError('no symbols fetched; no log or state written')
    bars = pd.concat(frames, axis=1).swaplevel(axis=1).sort_index().sort_index(axis=1)
    return bars, unavailable


def filtered(bars):
    index, _ = sessions(bars['Close'])
    return bars.loc[index]


def holidays(path):
    return {date.fromisoformat(line.split('#')[0].strip()) for line in path.read_text().splitlines()
            if line.split('#')[0].strip()}


def execution_date(as_of, bars, now):
    closed = holidays(FORWARD / 'nse_holidays.txt')
    if not any(d.year == as_of.year for d in closed):
        raise ValueError(f'no NSE holiday entries for {as_of.year}')
    if bars.empty or bars.index[-1].date() != as_of:
        raise ValueError('as-of must be the newest session in fetched data')
    for day in range(as_of.day + 1, calendar.monthrange(as_of.year, as_of.month)[1] + 1):
        d = as_of.replace(day=day)
        if d.weekday() < 5 and d not in closed:
            raise ValueError('as-of is not month-end: a later weekday is not a holiday')
    if now < datetime.combine(as_of, time(15, 30), IST):
        raise ValueError('log must run at or after 15:30 IST on as-of')
    d = as_of + timedelta(days=1)
    if d.year != as_of.year and not any(h.year == d.year for h in closed):
        # The December log trades in January: that year's holidays must be known first.
        raise ValueError(f'no NSE holiday entries for {d.year}; needed to find the execution session')
    while d.weekday() >= 5 or d in closed:
        d += timedelta(days=1)
    return d


def log_month(as_of, bars, unavailable, now=None):
    now = now or utcnow()
    month = month_name(as_of.strftime('%Y-%m'))
    path = FORWARD / f'{month}.json'
    if path.exists():
        raise FileExistsError(f'{path} exists; use log --publish {month} to retry publication')
    bars = filtered(bars)
    execution = execution_date(as_of, bars, now)
    closes, volumes = bars['Close'], bars['Volume']
    basket, benchmark, info = make_selectors(closes, volumes)
    details = info(as_of)
    if details['eligible'] < GATE_MIN_ELIGIBLE:
        raise ValueError(f'eligible gate: {details["eligible"]} < 50 at {as_of}')
    eligible = details['eligible_set']
    signals = signal(closes, as_of)
    payload = bars.to_csv(float_format='%.17g').encode()
    record = {'month': month, 'as_of': as_of.isoformat(), 'execution_session': execution.isoformat(),
              'fetch_time_utc': now.isoformat(), 'universe_sha256': sha(UNIVERSE.read_bytes()),
              'bars_sha256': sha(payload), 'code_commit': git('rev-parse', 'HEAD'),
              'eligible_names': sorted(eligible), 'signals': {s: float(signals[s]) for s in sorted(eligible)},
              'basket': basket(closes, as_of, eligible), 'benchmark': benchmark(closes, as_of, eligible),
              'excluded_by_rule': details['failed'], 'unavailable': unavailable}
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    snapshot = SNAPSHOTS / f'{month}.csv'
    # A partial previous write may leave the immutable payload but never a different one.
    if snapshot.exists():
        if snapshot.read_bytes() != payload:
            raise ValueError('existing snapshot differs; refusing replacement')
    else:
        with snapshot.open('xb') as f:
            f.write(payload)
    manifest = FORWARD / 'MANIFEST.jsonl'
    line = json.dumps({'month': month, 'snapshot': str(snapshot.relative_to(ROOT)),
                       'sha256': sha(payload)}, sort_keys=True) + '\n'
    existing = manifest.read_text() if manifest.exists() else ''
    entries = [json.loads(x) for x in existing.splitlines()]
    matches = [x for x in entries if x['month'] == month]
    if matches and matches != [json.loads(line)]:
        raise ValueError('manifest already contains a different snapshot for this month')
    if not matches:
        atomic(manifest, (existing + line).encode())
    with path.open('xb') as f:
        f.write(encoded(record))
    return path


def repo_name():
    remote = git('remote', 'get-url', 'origin')
    match = re.fullmatch(r'(?:https://github.com/|git@github.com:)([\w.-]+/[\w.-]+?)(?:\.git)?/?', remote)
    if not match:
        raise ValueError('origin must identify a GitHub repository')
    return match[1]


def gh(*args):
    return subprocess.check_output(['gh', 'api', *args], cwd=ROOT, text=True)


def remote_log(commit, path):
    """Confirm main ancestry and exact file bytes; return GitHub's HTTP Date."""
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('invalid receipt commit')
    repo = repo_name()
    response = gh('--include', '-H', 'Cache-Control: no-cache', f'repos/{repo}/commits/{commit}')
    headers, body = response.replace('\r\n', '\n').split('\n\n', 1)
    if json.loads(body)['sha'] != commit:
        raise ValueError('GitHub returned a different commit')
    stamp = next(line.split(':', 1)[1].strip() for line in headers.splitlines()
                 if line.lower().startswith('date:'))
    published = parsedate_to_datetime(stamp).astimezone(timezone.utc)
    comparison = json.loads(gh(f'repos/{repo}/compare/{commit}...main'))
    if comparison['status'] not in ('ahead', 'identical'):
        raise ValueError('receipt commit is not on origin main')
    content = json.loads(gh(f'repos/{repo}/contents/{path.relative_to(ROOT).as_posix()}?ref={commit}'))
    if content.get('encoding') != 'base64':
        raise ValueError('GitHub did not return the month file')
    if sha(base64.b64decode(content['content'])) != sha(path.read_bytes()):
        raise ValueError('remote month file hash mismatch')
    return published


def publication_guard(month):
    if git('branch', '--show-current') != 'main':
        raise ValueError('monthly publication must run on main after the tool is merged')
    allowed = {f'research/momentum/forward/{month}.json',
               f'research/momentum/forward/{month}.receipt.json', 'research/momentum/forward/MANIFEST.jsonl'}
    changed = set(git('diff', 'HEAD', '--name-only').splitlines())
    ahead = set(git('diff', 'origin/main...HEAD', '--name-only').splitlines())
    if (changed | ahead) - allowed:
        raise ValueError('unrelated local changes/commits; refusing to publish them')


def publish(month):
    month_name(month)
    publication_guard(month)
    path = FORWARD / f'{month}.json'
    manifest = FORWARD / 'MANIFEST.jsonl'
    if not path.exists():
        raise FileNotFoundError(path)
    receipt = FORWARD / f'{month}.receipt.json'
    paths = [str(p.relative_to(ROOT)) for p in (path, manifest)]
    try:
        tracked = git('ls-files', '--', paths[0])
        if not tracked or git('diff', 'HEAD', '--', *paths):
            if tracked:
                raise ValueError('committed month or manifest modified; refusing to rewrite publication')
            git('add', '--', *paths)
            git('commit', '--only', '-m', f'momentum: log {month}', '--', *paths)
        commit = git('log', '-1', '--format=%H', '--', paths[0])
        git('push', 'origin', 'HEAD:main')
        stamp = remote_log(commit, path)
        if receipt.exists():
            if read(receipt)['commit_sha'] != commit:
                raise ValueError('receipt refers to a different log commit')
        else:
            receipt_path = str(receipt.relative_to(ROOT))
            saved = (json.loads(git('show', f'HEAD:{receipt_path}'))
                     if git('ls-files', '--', receipt_path) else None)
            if saved is not None and saved['commit_sha'] != commit:
                raise ValueError('committed receipt refers to another log')
            with receipt.open('xb') as f:
                f.write(encoded(saved or {'commit_sha': commit, 'published_at_utc': stamp.isoformat()}))
        receipt_path = str(receipt.relative_to(ROOT))
        if not git('ls-files', '--', receipt_path):
            git('add', '--', receipt_path)
            git('commit', '--only', '-m', f'momentum: publication receipt {month}', '--', receipt_path)
        git('push', 'origin', 'HEAD:main')
    except (subprocess.CalledProcessError, ValueError, KeyError, StopIteration) as exc:
        # A failed receipt push must not make a local-only receipt acceptable to mark.
        if receipt.exists():
            receipt.unlink()
        raise RuntimeError(f'publication failed: {exc}; retry log --publish {month}; month file unchanged') from exc
    print(f'Published {month}; receipt {receipt}')


def is_late(month, record):
    receipt = FORWARD / f'{month}.receipt.json'
    if not receipt.exists():
        return True
    try:
        r = read(receipt)
        stamp = datetime.fromisoformat(r['published_at_utc'])
        remote_log(r['commit_sha'], FORWARD / f'{month}.json')
        deadline = datetime.combine(date.fromisoformat(record['execution_session']), time(9, 15), IST)
        return stamp >= deadline
    except (subprocess.CalledProcessError, ValueError, KeyError, StopIteration, TypeError):
        return True


def load_snapshot(month, record):
    payload = (SNAPSHOTS / f'{month}.csv').read_bytes()
    if sha(payload) != record['bars_sha256']:
        raise ValueError('frozen log snapshot hash mismatch')
    return pd.read_csv(io.BytesIO(payload), header=[0, 1], index_col=0, parse_dates=True,
                       float_precision='round_trip')


def fill(account, targets, bars, as_of, execution, remembered):
    """Resolve registered held inputs, then call the unchanged shared rebalance step."""
    c, o, v = bars['Close'].copy(), bars['Open'], bars['Volume']
    history = point_in_time_adv(c.loc[:str(as_of)], v.loc[:str(as_of)],
                                [d.date() for d in c.index if d.date() <= as_of])
    latest = dict(remembered)
    for sym in c:
        valid = c.loc[c.index < pd.Timestamp(execution), sym].dropna()
        item = dict(latest.get(sym, {}))
        if len(valid):
            item.update(close=float(valid.iloc[-1]), close_date=valid.index[-1].date().isoformat())
        for d in reversed(history):
            if sym in history[d]:
                item.update(adv=history[d][sym], adv_date=d.isoformat())
                break
        latest[sym] = item
    adv = dict(history[as_of])
    fallback, carry = {}, []
    for sym in account['holdings']:
        item = latest[sym]
        if sym not in c or c.loc[c.index < pd.Timestamp(execution), sym].dropna().empty:
            c.loc[pd.Timestamp(item['close_date']), sym] = item['close']
        if _open_px(o, sym, execution) is None:
            carry.append({'symbol': sym, 'source_date': item['close_date'], 'price': item['close']})
        elif sym not in adv:
            adv[sym] = item['adv']
            fallback[sym] = {'symbol': sym, 'source_date': item['adv_date'], 'adv': item['adv']}
    c.sort_index(inplace=True)
    step = _rebalance_step(account, targets, adv, c, o, execution,
                           CostModel(brokerage_per_trade=0), SPREAD_BPS, prior_close_carry=True)
    if step is None:
        raise ValueError('no target can trade; no state written')
    new, info = step
    invested = sum(q * _carry_px(c, o, s, execution, prior_close=True) for s, q in new['holdings'].items())
    equity = new['cash'] + invested
    fraction = invested / equity
    if not .99 <= fraction <= 1:
        raise ValueError(f'invested gate: {fraction} at {as_of}; no state written')
    traded = set(info['traded_names'])
    uses = {'held_adv_fallback': [fallback[s] for s in sorted(traded & fallback.keys())],
            'held_no_open': carry,
            'unheld_target_no_open': [s for s in info['skipped_buys'] if s not in account['holdings']],
            'resumed_held_trades': sorted(traded & set(account.get('carried', []))),
            'carried_invested': list(info['carried'])}
    new.update(equity=equity, carried=info['carried'])
    return new, {'costs': info['costs'], 'turnover': info['traded_notional'] / info['equity_pre'],
                 'invested_fraction': fraction, 'carried_names': info['carried'],
                 'amendment_3_uses': uses, 'amendment_3_counts': {k: len(x) for k, x in uses.items()}}, latest


def mark_month(month, fresh, now=None):
    month_name(month)
    state_path = FORWARD / 'state.json'
    state = read(state_path) if state_path.exists() else {'accounts': {}, 'months': [], 'inputs': {}}
    if any(r['month'] == month for r in state['months']):
        print(f'{month} already marked; no-op')
        return state
    expected = next_month(state['months'][-1]['month']) if state['months'] else FIRST
    if month != expected:
        raise ValueError(f'mark {expected} first; account state must stay continuous')
    rec = read(FORWARD / f'{month}.json')
    as_of, execution = date.fromisoformat(rec['as_of']), date.fromisoformat(rec['execution_session'])
    if (now or utcnow()) < datetime.combine(execution, time(15, 30), IST):
        raise ValueError('mark after execution session closes at 15:30 IST')
    fresh = filtered(fresh)
    later = fresh.index[fresh.index > pd.Timestamp(as_of)]
    if len(later) == 0 or later[0].date() != execution:
        raise ValueError('fresh next session does not match logged execution session; no state written')
    frozen = load_snapshot(month, rec)
    bars = pd.concat([frozen, fresh.loc[[pd.Timestamp(execution)]]]).sort_index()
    if len(rec['eligible_names']) < GATE_MIN_ELIGIBLE:
        raise ValueError('eligible gate: fewer than 50; no state written')
    row = {'month': month, 'execution_session': execution.isoformat(), 'late': is_late(month, rec),
           'eligible_count': len(rec['eligible_names']), 'period_returns': None,
           'execution_bars_sha256': sha(fresh.loc[[pd.Timestamp(execution)]].to_csv(float_format='%.17g').encode())}
    before = state['accounts']
    after, metrics, inputs = {}, {}, {}
    for side in ('basket', 'benchmark'):
        account = before.get(side, {'cash': BUDGET, 'holdings': {}})
        after[side], metrics[side], inputs[side] = fill(account, rec[side], bars, as_of, execution,
                                                       state['inputs'].get(side, {}))
    if state['months']:
        previous = state['months'][-1]
        if not previous['late']:
            b = after['basket']['equity'] / before['basket']['equity'] - 1
            m = after['benchmark']['equity'] / before['benchmark']['equity'] - 1
            previous['period_returns'] = {'basket': b, 'benchmark': m, 'active': b - m}
        previous['period_ended_at'] = execution.isoformat()
    row.update(metrics)
    state['months'].append(row)
    state.update(accounts=after, inputs=inputs)
    atomic(state_path, encoded(state))
    print(f'Marked {month}; commit and push state.json after review.')
    return state


def report():
    state = read(FORWARD / 'state.json')
    lines = ['| Month | Status | Basket net | Benchmark net | Active net | Basket/benchmark costs | Basket/benchmark turnover | Basket/benchmark invested | Eligible |',
             '|---|---|---:|---:|---:|---|---|---|---:|']
    for r in state['months']:
        returns = r['period_returns'] or {}
        status = ('final rebalance' if r['month'] == LAST else
                  'missed' if r['late'] else ('complete' if returns else 'pending'))
        values = [r['month'], status] + [str(returns.get(k, '—')) for k in ('basket', 'benchmark', 'active')]
        values += [f"{r['basket'][k]} / {r['benchmark'][k]}" for k in ('costs', 'turnover', 'invested_fraction')]
        lines.append('| ' + ' | '.join(values + [str(r['eligible_count'])]) + ' |')
    if state['months'][-1]['month'] == LAST:
        completed = state['months'][:-1]
        active = [r['period_returns']['active'] for r in completed if r['period_returns'] is not None]
        missed = sum(r['late'] for r in completed)
        lines += ['', f'On-time periods: {len(active)}; missed: {missed}.']
        if len(active) >= 18:
            ci = stationary_bootstrap_sharpe_ci(active, n_bootstrap=2000, confidence=.95,
                                               mean_block_length=3, periods_per_year=12, seed=2026, risk_free=0)
            wording = 'consistent with the backtest' if ci['sharpe'] > 0 else 'not consistent'
            lines += [f"IR: {ci['sharpe']}; bootstrap 95% interval [{ci['ci_lower']}, {ci['ci_upper']}]. {wording}.",
                      '24 observations give an interval half-width near 1.4 in IR; this cannot confirm an edge of ordinary size.',
                      'The historical result remains a candidate, not a proven edge.']
    atomic(FORWARD / 'REPORT.md', ('\n'.join(lines) + '\n').encode())


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    log = sub.add_parser('log')
    group = log.add_mutually_exclusive_group(required=True)
    group.add_argument('--as-of', type=date.fromisoformat)
    group.add_argument('--publish', type=month_name)
    mark = sub.add_parser('mark')
    mark.add_argument('--month', required=True, type=month_name)
    sub.add_parser('report')
    args = p.parse_args(argv)
    try:
        if args.command == 'report':
            report()
        elif args.command == 'log' and args.publish:
            publish(args.publish)
        elif args.command == 'log':
            month = month_name(args.as_of.strftime('%Y-%m'))
            publication_guard(month)
            if (FORWARD / f'{month}.json').exists():
                raise FileExistsError('month exists; use log --publish')
            _, tickers = read_universe(UNIVERSE)
            bars, unavailable = fetch_bars(args.as_of, tickers)
            log_month(args.as_of, bars, unavailable)
            publish(month)
        else:
            if (FORWARD / 'state.json').exists() and any(r['month'] == args.month for r in read(FORWARD / 'state.json')['months']):
                print(f'{args.month} already marked; no-op')
                return 0
            rec = read(FORWARD / f'{args.month}.json')
            _, tickers = read_universe(UNIVERSE)
            bars, _ = fetch_bars(date.fromisoformat(rec['as_of']), tickers)
            mark_month(args.month, bars)
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'[REFUSED] {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
