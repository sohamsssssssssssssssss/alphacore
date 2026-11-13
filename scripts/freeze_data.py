#!/usr/bin/env python3.11
"""Fetch once; never silently replace a manifest's frozen payloads."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'data_snapshots/2026-11'
sys.path.insert(0, str(ROOT / 'backend'))
from data.nifty50_symbols import NIFTY50_SYMBOLS


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(entry):
    if entry['kind'] == 'earnings':
        frame = yf.Ticker(entry['ticker']).earnings_dates
    else:
        frame = yf.download(entry['ticker'], start='2020-08-14', end='2026-08-14',
                            interval='1d', auto_adjust=True, progress=False)
    if frame is None or frame.empty:
        raise RuntimeError(f"No {entry['kind']} data for {entry['ticker']}")
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame = frame.sort_index()
    frame.index.name = 'Date'
    return frame


def verify(directory=SNAPSHOT):
    manifest = json.loads((directory / 'MANIFEST.json').read_text())
    for name, entry in manifest['files'].items():
        path = directory / name
        if not path.is_file() or sha256(path) != entry['sha256']:
            raise RuntimeError(f'Frozen snapshot missing or hash mismatch: {path}')
    return manifest


def freeze():
    SNAPSHOT.mkdir(parents=True, exist_ok=True)
    manifest_path = SNAPSHOT / 'MANIFEST.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for name, entry in manifest['files'].items():
            path = SNAPSHOT / name
            if path.exists():
                if sha256(path) != entry['sha256']:
                    raise RuntimeError(f'Hash mismatch; refusing to replace {path}')
                continue
            # A missing payload may be recovered only if it matches the committed hash.
            with tempfile.TemporaryDirectory(dir=SNAPSHOT) as temp:
                candidate = Path(temp) / name
                download(entry).to_csv(candidate)
                if sha256(candidate) != entry['sha256']:
                    raise RuntimeError(f'Provider cannot recover frozen hash for {name}; manifest unchanged')
                candidate.replace(path)
        verify()
        print(f"Verified {len(manifest['files'])} frozen files; no refetch of existing payloads")
        return
    files, missing = {}, {}
    requests = [(s + '.csv', {'ticker': s + '.NS', 'kind': 'daily'}) for s in NIFTY50_SYMBOLS]
    requests += [('NSEI.csv', {'ticker': '^NSEI', 'kind': 'index'})]
    requests += [('earnings_' + s + '.csv', {'ticker': s + '.NS', 'kind': 'earnings'})
                 for s in ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK']]
    for name, entry in requests:
        fetched_at = datetime.now(timezone.utc).isoformat()
        try:
            frame = download(entry)
        except Exception as exc:
            missing[name] = {'ticker': entry['ticker'], 'reason': str(exc), 'fetch_timestamp': fetched_at}
            print(f'UNAVAILABLE {name}: {exc}', flush=True)
            continue
        path = SNAPSHOT / name
        frame.to_csv(path)
        files[name] = entry | {'sha256': sha256(path), 'row_count': len(frame),
                              'first_date': str(frame.index.min()), 'last_date': str(frame.index.max()),
                              'fetch_timestamp': fetched_at, 'yfinance_version': yf.__version__,
                              'timezone': str(frame.index.tz) if frame.index.tz is not None else None}
        print(f"FROZEN {name}: {len(frame)} rows, {files[name]['first_date']} -> {files[name]['last_date']}", flush=True)
    if not files:
        raise RuntimeError('No snapshot files obtained; refusing an empty manifest')
    manifest = {'schema_version': 1, 'fetch_timestamp': datetime.now(timezone.utc).isoformat(),
                'yfinance_version': yf.__version__, 'pandas_version': pd.__version__,
                'daily_request': {'start': '2020-08-14', 'end_exclusive': '2026-08-14', 'auto_adjust': True},
                'requested_universe': NIFTY50_SYMBOLS, 'files': files, 'unavailable': missing,
                'hourly_status': 'not reproducible: source data no longer obtainable (Yahoo 730-day retention)',
                'notes': ['CSV payloads remain local/gitignored; only this manifest is committed.',
                          'Index and earnings responses are frozen for descriptive benchmarks and unchanged PEAD logic.',
                          'This snapshot is newly fetched, not the missing v1 CSV snapshot.']}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    verify()
    print(f'Committed-manifest candidate: {manifest_path}; {len(files)} files')


if __name__ == '__main__':
    if sys.version_info[:2] != (3, 11):
        raise SystemExit('Python 3.11 required')
    freeze()
