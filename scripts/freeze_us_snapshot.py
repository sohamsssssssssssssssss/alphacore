#!/usr/bin/env python3.11
"""
Freeze Yahoo daily OHLCV for the S&P 100 universe (OOS Arm A data).

Sibling of freeze_data.py, using the same manifest layout. Fetches once, never
overwrites a payload, and never substitutes a symbol: a ticker with no data is
recorded under "unavailable".

Input:  data_snapshots/us-2026-11/universe.txt (committed before this runs)
Output: data_snapshots/us-2026-11/<SYMBOL>.csv (gitignored) and MANIFEST.json (tracked)
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data_snapshots" / "us-2026-11"
START = "2010-01-01"
END_EXCLUSIVE = "2026-10-31"  # yfinance end is exclusive: includes 2026-10-30


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_universe(path: Path) -> list[str]:
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")]


def yahoo_symbol(ticker: str) -> str:
    return ticker.replace(".", "-")


def download(symbol: str) -> pd.DataFrame:
    frame = yf.download(symbol, start=START, end=END_EXCLUSIVE, interval="1d",
                        auto_adjust=True, progress=False)
    if frame is None or frame.empty:
        raise RuntimeError(f"no daily data for {symbol}")
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame = frame.sort_index()
    frame.index.name = "Date"
    return frame


def verify(directory: Path = SNAPSHOT) -> dict:
    manifest = json.loads((directory / "MANIFEST.json").read_text())
    for name, entry in manifest["files"].items():
        path = directory / name
        if not path.is_file() or sha256(path) != entry["sha256"]:
            raise RuntimeError(f"frozen snapshot missing or hash mismatch: {path}")
    return manifest


def freeze() -> None:
    universe_path = SNAPSHOT / "universe.txt"
    manifest_path = SNAPSHOT / "MANIFEST.json"
    tickers = read_universe(universe_path)

    if manifest_path.exists():
        manifest = verify()
        print(f"Already frozen: verified {len(manifest['files'])} files, no refetch.")
        return
    stray = [t for t in tickers if (SNAPSHOT / f"{yahoo_symbol(t)}.csv").exists()]
    if stray:
        raise RuntimeError(f"CSVs exist without a manifest (refusing to refetch): {stray[:5]}")

    files, unavailable = {}, {}
    for ticker in tickers:
        sym = yahoo_symbol(ticker)
        fetched_at = datetime.now(timezone.utc).isoformat()
        try:
            frame = download(sym)
        except Exception as exc:
            unavailable[ticker] = {"yahoo_symbol": sym, "reason": str(exc), "fetch_timestamp": fetched_at}
            print(f"UNAVAILABLE {ticker} ({sym}): {exc}", flush=True)
            continue
        name = f"{sym}.csv"
        path = SNAPSHOT / name
        frame.to_csv(path)
        files[name] = {
            "kind": "daily", "ticker": sym, "sha256": sha256(path), "row_count": len(frame),
            "first_date": str(frame.index.min()), "last_date": str(frame.index.max()),
            "fetch_timestamp": fetched_at, "yfinance_version": yf.__version__,
            "timezone": str(frame.index.tz) if frame.index.tz is not None else None,
        }
        print(f"FROZEN {name}: {len(frame)} rows, {files[name]['first_date']} -> {files[name]['last_date']}",
              flush=True)

    if not files:
        raise RuntimeError("no snapshot files obtained; refusing an empty manifest")
    manifest = {
        "schema_version": 1,
        "fetch_timestamp": datetime.now(timezone.utc).isoformat(),
        "yfinance_version": yf.__version__,
        "pandas_version": pd.__version__,
        "daily_request": {"start": START, "end_exclusive": END_EXCLUSIVE, "auto_adjust": True},
        "universe_file": "universe.txt",
        "universe_sha256": sha256(universe_path),
        "requested_universe": tickers,
        "files": files,
        "unavailable": unavailable,
        "notes": ["CSV payloads remain local/gitignored; only this manifest is committed.",
                  "Symbols with no data are listed as unavailable and are not substituted.",
                  "Current S&P 100 membership is applied to the past (survivorship; see protocol)."],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    verify()
    print(f"Wrote {manifest_path}: {len(files)} frozen, {len(unavailable)} unavailable")


if __name__ == "__main__":
    if sys.version_info[:2] != (3, 11):
        raise SystemExit("Python 3.11 required")
    freeze()
