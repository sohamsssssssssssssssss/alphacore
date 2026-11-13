"""
AlphaCore — Upstox Sandbox Paper-Trading Harness (ISOLATED).

This package is intentionally separate from the live AlphaCore trading path:
  * It only ever talks to the Upstox SANDBOX API (https://api-sandbox.upstox.com)
    using a dedicated sandbox access token (generated from a sandbox app in the
    Upstox developer console — NEVER a live OAuth token).
  * It never imports, mutates, or drives the live broker/paper-trading modules
    (backend/execution, backend/paper_runner.py, etc.).
  * All data it touches is read-only: yfinance daily bars for signal computation
    and its own append-only JSONL/raw logs under backend/sandbox/logs/.

Run from the repo `backend/` directory:
    python3.11 -m sandbox.harness --dry-run
    python3.11 -m sandbox.harness --rebalance-date 2026-08-31   # needs UPSTOX_SANDBOX_TOKEN
"""
