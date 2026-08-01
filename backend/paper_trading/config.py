"""Locked strategy parameters and harness configuration.

The strategy parameters below are LOCKED from the universe-expansion / K-expansion
experiments (backend/experiments/universe_expansion_experiment.py) and must not be
changed. This experiment validates execution cost only.

Source of truth for the locked config:
  UNIVERSE_EXPANSION_EXPERIMENT_PROTOCOL.md  (49-symbol, K=1, daily bars, monthly)
  K_EXPANSION_EXPERIMENT_PROTOCOL.md         (K=1 daily 49-sym config, CI [-3.14, +0.05])
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Locked strategy parameters (do not change) ─────────────────────────────
LOOKBACK_N = 20            # trailing-return lookback, trading days
K = 1                      # 1 long + 1 short position
REBALANCE_INTERVAL = 21    # rebalance every 21 TRADING days (~monthly)
POSITION_SIZE_PCT = 0.10   # 10% of equity per leg
INITIAL_CAPITAL = 100000.0 # matches backtest

# ── Upstox endpoints (sandbox only for orders) ─────────────────────────────
SANDBOX_BASE = "https://sandbox.upstox.com"          # order placement — ONLY this host
LIVE_API_BASE = "https://api.upstox.com"             # read-only market data ONLY

# ── Order shape (mirrors backtest's marketable-fill assumption) ────────────
ORDER_PRODUCT_LONG = "D"     # delivery for buy-and-hold long leg
ORDER_PRODUCT_SHORT = "I"    # intraday product for short leg (cash segment can only
                             # short intraday; backtest already assumes no borrow cost)
ORDER_VALIDITY = "DAY"
ORDER_TYPE = "MARKET"
ORDER_TAG = "alphacore_paper_v1"
ORDER_MARKET_PROTECTION = -1  # Upstox default (automatic market protection)

# ── Execution timing (IST) ─────────────────────────────────────────────────
REBALANCE_WINDOW_START = "15:10"   # rebalance orders submitted in this window,
REBALANCE_WINDOW_END = "15:20"     # ~10 min before the 15:30 close
CLOSE_CAPTURE_TIME = "15:32"       # daily close snapshot for the signal series
LOOP_SLEEP_TRADING = 30            # seconds between cycles during market hours
LOOP_SLEEP_OFFHOURS = 300          # seconds between cycles outside market hours
FILL_POLL_INTERVAL = 10            # seconds between order-status polls
FILL_POLL_TIMEOUT = 420            # max seconds to wait for a terminal order state
FILL_SANITY_MAX_DEVIATION = 0.05   # fill > 5% from live mid flagged as suspect

# ── Paths ───────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = Path(os.getenv("PAPER_STATE_DIR", REPO_ROOT / "states" / "paper_trading"))
DATA_DIR_50 = REPO_ROOT / "backend" / "data" / "nifty50_data"
LOG_FILE = STATE_DIR / "logs" / "events.jsonl"
TOKENS_FILE = STATE_DIR / "tokens.json"
STATE_FILE = STATE_DIR / "state.json"
INSTRUMENTS_FILE = STATE_DIR / "instruments.json"
CLOSE_HISTORY_FILE = STATE_DIR / "close_history.json"
KILL_FILE = STATE_DIR / "KILL"

# ── Auth (PAPER_* env vars, loaded from backend/paper_trading/.env) ────────
load_dotenv(Path(__file__).resolve().parent / ".env")

def get_env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default

# ── Guard rails ─────────────────────────────────────────────────────────────
def sandbox_url() -> str:
    """Base URL for order placement. Refuses to run against anything but sandbox."""
    url = get_env("PAPER_SANDBOX_URL", SANDBOX_BASE) or SANDBOX_BASE
    if not url.startswith("https://sandbox.upstox.com"):
        raise RuntimeError(
            f"REFUSING TO START: PAPER_SANDBOX_URL={url!r} is not the Upstox "
            f"sandbox host (https://sandbox.upstox.com). Sandbox-only policy."
        )
    return url.rstrip("/")


def marketdata_url() -> str:
    """Base URL for read-only market data (live host; never used for orders)."""
    return (get_env("PAPER_MARKETDATA_URL", LIVE_API_BASE) or LIVE_API_BASE).rstrip("/")


def slack_webhook() -> str | None:
    return get_env("SLACK_WEBHOOK_URL")


def fill_poll_timeout() -> int:
    return _env_int("PAPER_FILL_POLL_TIMEOUT", FILL_POLL_TIMEOUT)


def fill_sanity_max_deviation() -> float:
    return _env_float("PAPER_FILL_SANITY_MAX_DEVIATION", FILL_SANITY_MAX_DEVIATION)


def slack_notify(text: str) -> None:
    """Best-effort Slack alert (optional; matches repo convention in
    backend/monitoring/health_check.py). Never raises."""
    hook = slack_webhook()
    if not hook:
        return
    try:
        import requests
        requests.post(hook, json={"text": text}, timeout=10)
    except Exception:
        pass
