"""
AlphaCore top-quartile basket (k=12) monthly cross-sectional relative-strength
— Upstox sandbox paper-trading harness.

What it does, per rebalance (LAST trading day of month, default schedule):
  1. States the PRECOMMITTED HYPOTHESIS (basket_hypothesis.py) before touching data.
  2. Fetches NSE daily bars (yfinance) for the 49-symbol universe.
  3. Ranks by trailing 21-trading-day return as of the rebalance date and
     selects the TOP-QUARTILE basket (k = n_ranked // 4, 12 of 49) via the
     exact same selection function the Phase 1 backtest uses
     (basket_backtest.top_quartile). Prints the FULL ranking table.
  4. Builds the order plan (side, qty from budget, instrument token) and the
     backtest-assumed cost per leg (costs.py mirror of repo CostModel).
  5. If --dry-run: prints the complete plan and payload, makes NO API calls.
  6. Otherwise: places the sandbox order(s) via the raw Upstox SANDBOX API,
     logs every request/response verbatim (terminal + logs/raw_api_*.txt),
     then best-effort polls order-history/trades. Fill prices are taken ONLY
     from what the API returns; if the sandbox exposes no fill data the leg
     is recorded as fill_status=UNCONFIRMED — never synthesized.

Isolation: this harness never imports or drives live AlphaCore trading
modules; it only ever talks to api-sandbox.upstox.com with a sandbox token.

Run from backend/:
    python3.11 -m sandbox.harness --dry-run --rebalance-date 2026-08-31
    python3.11 -m sandbox.harness --rebalance-date 2026-08-31   # needs UPSTOX_SANDBOX_TOKEN
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

import pandas as pd
import requests

# Make sibling modules importable when run as `python -m sandbox.harness`
# from backend/ (mirrors conftest.py; keeps absolute imports consistent).
_SANDBOX_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_SANDBOX_DIR), "experiments"))
if _SANDBOX_DIR not in sys.path:
    sys.path.insert(0, _SANDBOX_DIR)

from basket_backtest import top_quartile  # same selection fn as the Phase 1 backtest
from costs import BACKTEST_ASSUMED_COST_PARAMS, assumed_total_cost, cost_in_bps, extract_observed_fill
from basket_hypothesis import BASKET_HYPOTHESIS_HEADER, HYPOTHESIS_HEADER
from instruments import DEFAULT_CACHE_PATH, resolve_instrument_keys
from prices import fetch_daily_bars, now_utc_iso
from rs_signal import LOOKBACK_TRADING_DAYS, previous_rebalance_date, rank_table, rebalance_dates
from universe import UNIVERSE_49
from upstox_sandbox import RawApiLogger, SANDBOX_BASE_URL, UpstoxSandboxClient

SCHEMA_VERSION = 1
DEFAULT_BUDGET_INR = 1_000_000.0
LOGS_DIR_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


# ---------------------------------------------------------------------------
# Order plan
# ---------------------------------------------------------------------------

def build_order_plan(closes, adv, rebalance: date, budget: float,
                     k: int | None = None, lookback: int = LOOKBACK_TRADING_DAYS) -> dict:
    """
    Build the top-quartile basket order plan as of `rebalance`.

    k=None -> top-quartile auto (n_ranked // 4, i.e. 12 of 49), matching the
    Phase 1 backtest exactly (basket_backtest.top_quartile). Returns dict with
    ranking table, target legs, and basket rotation context.
    """
    tbl = rank_table(closes, rebalance, lookback=lookback)
    targets = top_quartile(closes, rebalance, k=k, lookback=lookback)
    prev = previous_rebalance_date(closes, rebalance)

    legs = []
    n_targets = max(len(targets), 1)
    per_position = budget / n_targets
    for sym in targets:
        row = tbl.loc[sym]
        ref_price = float(closes[sym].loc[closes.index <= pd.Timestamp(rebalance)].iloc[-1])
        qty = max(1, int(per_position // ref_price)) if ref_price > 0 else 0
        legs.append({
            "symbol": sym,
            "side": "BUY",
            "qty": int(qty),
            "ref_price": ref_price,
            "ret_21d": float(row["ret_21d"]),
            "rank": int(row["rank"]),
            "adv_inr": float(adv.get(sym, 0.0)),
            "assumed_cost_inr": assumed_total_cost(ref_price, qty, adv.get(sym), "BUY") if qty > 0 else 0.0,
        })

    prev_basket = top_quartile(closes, prev, k=k, lookback=lookback) if prev else []
    prev_prices: dict[str, float] = {}
    if prev_basket and prev is not None:
        for sym in prev_basket:
            s = closes[sym]
            prev_rows = s.loc[s.index <= pd.Timestamp(prev)]
            if len(prev_rows) > 0:
                prev_prices[sym] = float(prev_rows.iloc[-1])
    return {
        "rebalance_date": rebalance.isoformat(),
        "previous_rebalance_date": prev.isoformat() if prev else None,
        "previous_basket": prev_basket,
        "previous_basket_prices": prev_prices,
        "k": len(targets),
        "ranking": tbl.reset_index().rename(columns={"index": "symbol"}).to_dict("records"),
        "legs": legs,
    }


def print_ranking(tbl_rows: list[dict], limit: int | None = None) -> None:
    print("\n[PLAN] Cross-sectional relative-strength ranking (trailing 21 trading-day return)")
    print(f"[PLAN] {'rank':>4}  {'symbol':<12} {'ret_21d':>10} {'has_data':>8}")
    for r in tbl_rows:
        print(f"[PLAN] {r['rank']:>4}  {str(r['symbol']):<12} {r['ret_21d']:>10.4f} {str(r['has_data']):>8}")
        if limit and int(r["rank"]) >= limit:
            print(f"[PLAN] ... (remaining {len(tbl_rows) - limit} rows omitted; full table in JSONL log)")
            break


# ---------------------------------------------------------------------------
# Instrument key resolution
# ---------------------------------------------------------------------------

def resolve_instrument_key(symbol: str, keys: dict[str, str]) -> str:
    """Return the real Upstox instrument_key from the instrument master lookup.

    FAILS LOUD if the symbol is missing — there is deliberately no fallback to
    guessed numeric tokens: a guessed key that the API silently rejects is
    worse than an explicit error before any order is placed.
    """
    key = keys.get(symbol)
    if not key:
        raise RuntimeError(
            f"FAIL-LOUD: no Upstox instrument_key for {symbol} in the instrument master lookup. "
            "Refusing to guess a numeric token; verify the symbol against the master before trading."
        )
    return key


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def execute_rebalance(plan: dict, client: UpstoxSandboxClient, raw: RawApiLogger,
                      order_type: str, limit_price: float | None,
                      is_amo: bool, place_rotation_sells: bool,
                      instrument_keys: dict[str, str]) -> list[dict]:
    print("\n[AUTH] Checking sandbox token (best-effort; profile endpoint may not be sandbox-enabled)...")
    auth = client.check_auth()
    print(f"[AUTH] status={auth['status_code']} response={json.dumps(auth['response'])}")

    records: list[dict] = []
    # Optional rotation sells: names in the previous basket that left the new
    # basket. ref_price is each name's close on the previous rebalance date
    # (resolved in build_order_plan) so observed slippage on the sell is
    # computable if the sandbox ever returns a fill. qty is advisory (1): the
    # sandbox has no position tracking, so rotation sizing is a placeholder.
    if place_rotation_sells:
        held = {l["symbol"] for l in plan["legs"]}
        leaving = [s for s in plan.get("previous_basket", []) if s not in held]
        for sym in leaving:
            records.append(_place_leg(
                client, raw, plan, {
                    "symbol": sym,
                    "side": "SELL",
                    "qty": 1,
                    "ref_price": float(plan.get("previous_basket_prices", {}).get(sym) or 0.0),
                    "adv_inr": 0.0,
                    "assumed_cost_inr": 0.0,
                }, instrument_keys, order_type, limit_price, is_amo,
            ))

    for leg in plan["legs"]:
        records.append(_place_leg(client, raw, plan, leg, instrument_keys, order_type, limit_price, is_amo))
    return records


def _place_leg(client: UpstoxSandboxClient, raw: RawApiLogger, plan: dict, leg: dict,
               instrument_keys: dict[str, str], order_type: str, limit_price: float | None,
               is_amo: bool) -> dict:
    symbol = leg["symbol"]
    side = leg["side"]
    qty = int(leg["qty"]) if leg["qty"] > 0 else 1
    instrument_key = resolve_instrument_key(symbol, instrument_keys)
    price = float(limit_price or 0.0) if order_type == "LIMIT" else 0.0

    print(f"\n[ORDER] {side} {qty} x {symbol} ({instrument_key}) type={order_type} amo={is_amo}")

    try:
        result = client.place_order(
            quantity=qty,
            instrument_token=instrument_key,
            transaction_type=side,
            order_type=order_type,
            price=price,
            is_amo=is_amo,
            tag=f"alphacore-basket-{plan['rebalance_date']}",
        )
    except requests.RequestException as exc:
        # Transport-level failure: record it verbatim (raw logger already wrote
        # the request + error). Never crash the run and lose the audit trail.
        record = {
            "schema_version": SCHEMA_VERSION,
            "event": "order_leg",
            "rebalance_date": plan["rebalance_date"],
            "utc_timestamp": now_utc_iso(),
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "order_type": order_type,
            "instrument_token": instrument_key,
            "ref_price": leg.get("ref_price"),
            "adv_inr": leg.get("adv_inr"),
            "assumed_cost_inr": leg.get("assumed_cost_inr"),
            "assumed_cost_bps": round(cost_in_bps(float(leg.get("assumed_cost_inr", 0.0)),
                                                  float(leg.get("ref_price", 0.0) or 0.0), qty), 4),
            "place_status_code": None,
            "place_response": None,
            "order_id": None,
            "poll_order_history": None,
            "poll_order_trades": None,
            "fill_status": "TRANSPORT_ERROR",
            "fill_reason": str(exc),
            "fill_price": None,
            "fill_qty": None,
            "fill_timestamp": None,
            "observed_fees_inr": None,
            "observed_slippage_bps": None,
        }
        print(f"[ORDER] fill_status=TRANSPORT_ERROR {symbol}: {exc}")
        return record

    place_payload = result["response"]
    order_id = result["order_id"]
    status_code = result["status_code"]

    fill = extract_observed_fill(place_payload)
    if isinstance(place_payload, dict) and str(place_payload.get("status", "")).lower() != "success":
        fill_status = "REJECTED"
        fill_reason = json.dumps(place_payload, ensure_ascii=False)
    elif order_id:
        fill_status = "ACCEPTED"
        fill_reason = None
    else:
        fill_status = "UNCONFIRMED"
        fill_reason = json.dumps(place_payload, ensure_ascii=False)

    # Best-effort poll (sandbox does not expose these endpoints yet — raw responses logged).
    poll_hist = None
    poll_trades = None
    if order_id and not os.environ.get("SANDBOX_SKIP_POLLS"):
        print(f"[POLL] Order history for {order_id} (best-effort; may not be sandbox-enabled)...")
        hist_status, hist_payload = client.get_order_history(order_id)
        poll_hist = {"status": hist_status, "response": hist_payload}
        hist_fill = extract_observed_fill(hist_payload) if isinstance(hist_payload, dict) else None
        if hist_fill and hist_fill["fill_price"] is not None:
            fill = hist_fill
            fill_status = "CONFIRMED"
        print(f"[POLL] Order trades for {order_id} (best-effort; may not be sandbox-enabled)...")
        tr_status, tr_payload = client.get_order_trades(order_id)
        poll_trades = {"status": tr_status, "response": tr_payload}
        tr_fill = extract_observed_fill(tr_payload) if isinstance(tr_payload, dict) else None
        if tr_fill and tr_fill["fill_price"] is not None:
            fill = tr_fill
            fill_status = "CONFIRMED"

    observed_slippage = None
    if fill["fill_price"] is not None and leg.get("ref_price", 0) and leg["ref_price"] > 0:
        observed_slippage = round(
            (float(fill["fill_price"]) - float(leg["ref_price"])) / float(leg["ref_price"]) * 10000.0
            * (1.0 if side == "BUY" else -1.0), 4)

    record = {
        "schema_version": SCHEMA_VERSION,
        "event": "order_leg",
        "rebalance_date": plan["rebalance_date"],
        "utc_timestamp": now_utc_iso(),
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "order_type": order_type,
        "instrument_token": instrument_key,
        "ref_price": leg.get("ref_price"),
        "adv_inr": leg.get("adv_inr"),
        "assumed_cost_inr": leg.get("assumed_cost_inr"),
        "assumed_cost_bps": round(cost_in_bps(float(leg.get("assumed_cost_inr", 0.0)),
                                              float(leg.get("ref_price", 0.0) or 0.0), qty), 4),
        "place_status_code": status_code,
        "place_response": place_payload,
        "order_id": order_id,
        "poll_order_history": poll_hist,
        "poll_order_trades": poll_trades,
        "fill_status": fill_status,
        "fill_reason": fill_reason,
        "fill_price": fill["fill_price"],
        "fill_qty": fill["fill_qty"],
        "fill_timestamp": fill["fill_timestamp"],
        "observed_fees_inr": fill["observed_fees_inr"],
        "observed_slippage_bps": observed_slippage,
    }
    print(f"[ORDER] fill_status={fill_status} order_id={order_id} "
          f"fill_price={record['fill_price']} fill_qty={record['fill_qty']}")
    return record


# ---------------------------------------------------------------------------
# Logging (JSONL)
# ---------------------------------------------------------------------------

def write_jsonl(log_dir: str, name: str, records: list[dict]) -> str:
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, name)
    with open(path, "a", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    print(f"[LOG] wrote {len(records)} records -> {path}")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AlphaCore top-quartile basket (k=12) sandbox paper-trading harness (Upstox SANDBOX only)")
    p.add_argument("--rebalance-date", type=str, default=None,
                   help="Rebalance date (last trading day of month) as YYYY-MM-DD. Default: last trading day of current month.")
    p.add_argument("--auto", action="store_true",
                   help="Use the most recent scheduled month-end (last trading day of month) on/before today from the fetched calendar.")
    p.add_argument("--dry-run", action="store_true",
                   help="Compute the signal + order plan and print it. Makes NO sandbox API calls.")
    p.add_argument("--budget", type=float, default=DEFAULT_BUDGET_INR,
                   help="Total notional budget split across target holdings (default 1,000,000 INR).")
    p.add_argument("--k", type=int, default=None,
                   help="Basket size; default: top-quartile (n_ranked // 4, i.e. 12 of 49) — same as the Phase 1 backtest.")
    p.add_argument("--order-type", choices=["MARKET", "LIMIT"], default="MARKET")
    p.add_argument("--limit-price", type=float, default=None, help="Required if --order-type LIMIT.")
    p.add_argument("--is-amo", action="store_true",
                   help="Send is_amo=true (after-market order; sandbox ignores it per Upstox docs).")
    p.add_argument("--place-rotation-sells", action="store_true",
                   help="Also place SELL legs for names leaving the previous basket (sandbox has no position tracking, so off by default).")
    p.add_argument("--refresh-instruments", action="store_true",
                   help="Re-download the Upstox instrument master even if a fresh cache exists in instruments_cache.json.")
    p.add_argument("--logs-dir", default=LOGS_DIR_DEFAULT)
    p.add_argument("--token", default=None, help="Sandbox access token (or set UPSTOX_SANDBOX_TOKEN).")
    p.add_argument("--base-url", default=SANDBOX_BASE_URL, help=argparse.SUPPRESS)
    return p.parse_args(argv)


def effective_basket_k(closes, k: int | None) -> int | None:
    """
    Basket size the run will actually use, computed BEFORE any order is placed.

    k=None -> top-quartile auto (n_ranked // 4, matching basket_backtest.top_quartile),
    so the precommitted-hypothesis print can gate on the mode. Pure rank-table
    arithmetic — no cost or selection logic involved.
    """
    if k is not None:
        return k
    ranked = [s for s, row in rank_table(closes, closes.index.max().date()).iterrows()
              if bool(row["has_data"])]
    return max(1, len(ranked) // 4)


def hypothesis_header_for_k(k: int | None) -> tuple[str, str]:
    """
    Pick the precommitted-hypothesis banner for the run's basket size.

    The harness now runs the basket config, so the BASKET hypothesis is the
    primary banner whenever k is auto (None) or any multi-name basket
    (k > 1). Only an explicit k=1 (the historical single-name config) prints
    the K=1 hypothesis. This function is also the single gate the session
    log records (hypothesis_mode), so precommit discipline is enforced by
    import, not by copy-paste.
    """
    if k == 1:
        return HYPOTHESIS_HEADER, "k1"
    return BASKET_HYPOTHESIS_HEADER, "basket"


def resolve_rebalance_date(closes, args) -> date:
    """
    Resolve the rebalance date.

    With --auto, returns the most recent scheduled month-end (last trading day
    of month) on/before today that exists in the fetched trading calendar. If
    run mid-month, that is the previous month's month-end — the calendar only
    contains dates through today, so the current month's month-end is not yet
    known. The resolved date is always printed for verification.
    """
    if args.rebalance_date:
        return date.fromisoformat(args.rebalance_date)
    today = date.today()
    dates = rebalance_dates(closes, today, months_back=2)
    if not dates:
        raise RuntimeError("no rebalance date resolvable from fetched calendar")
    return dates[-1]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Pre-commit: hypothesis must be printed before ANY sandbox data is pulled.
    # k is resolved from the fetched closes AFTER the fetch, so for the print
    # we gate on the CLI flag only (default basket); the exact k the run uses
    # is resolved and cross-checked right after the fetch, still before any
    # order is placed — a mismatch re-prints the correct banner.
    header, mode = hypothesis_header_for_k(args.k)
    print(header)
    print(f"\n[RUN] python3.11 {sys.argv[0]} {' '.join(argv) if argv else ''}")
    print(f"[RUN] sandbox base URL: {args.base_url}")
    print(f"[RUN] dry-run: {args.dry_run} | budget INR: {args.budget:,.0f} | "
          f"order-type: {args.order_type} | is_amo: {args.is_amo}")
    print(f"[RUN] hypothesis mode: {mode} (k_requested={args.k}) | "
          f"backtest-assumed cost params: {json.dumps(BACKTEST_ASSUMED_COST_PARAMS)}")

    session_tag = f"rb_{args.rebalance_date or 'auto'}"
    raw = RawApiLogger(args.logs_dir, session_tag)

    # 1) Data
    print(f"\n[DATA] Fetching daily bars for {len(UNIVERSE_49)}-symbol universe (Nifty 50 minus SBILIFE)...")
    closes, adv = fetch_daily_bars(UNIVERSE_49, as_of=date.today())
    if closes.empty:
        print("[FATAL] no price data; aborting", file=sys.stderr)
        raw.close()
        return 1

    rebalance = resolve_rebalance_date(closes, args)
    print(f"\n[SCHEDULE] Rebalance date: {rebalance} (last trading day of month per schedule)")

    # Cross-check the hypothesis banner against the ACTUAL basket size the run
    # will use (the CLI flag may be None for auto top-quartile -> k=12). If the
    # resolved mode differs from the pre-fetch gate, print the correct banner
    # now — still before any order is placed.
    eff_k = effective_basket_k(closes, args.k)
    header2, mode2 = hypothesis_header_for_k(eff_k)
    print(f"[PLAN] effective basket size: k={eff_k} (hypothesis banner: {mode2})")
    if mode2 != mode:
        print(header2)

    # 2) Signal + plan
    plan = build_order_plan(closes, adv, rebalance, args.budget, k=args.k)
    print_ranking(plan["ranking"], limit=20)

    # Resolve REAL Upstox instrument keys for every planned leg (+ previous
    # basket, for rotation sells) from Upstox's published instrument master
    # (cached in instruments_cache.json). FAILS LOUD if any symbol is missing
    # — no numeric-token fallback, so a guessed key can never reach the API.
    resolve_symbols = [leg["symbol"] for leg in plan["legs"]]
    for sym in plan.get("previous_basket", []):
        if sym not in resolve_symbols:
            resolve_symbols.append(sym)
    instrument_keys = resolve_instrument_keys(resolve_symbols, DEFAULT_CACHE_PATH,
                                              force=args.refresh_instruments)
    print(f"\n[PLAN] previous rebalance: {plan['previous_rebalance_date']} "
          f"-> previous basket: {plan['previous_basket']}")
    print(f"[PLAN] top-quartile basket (k={plan['k']}): {[l['symbol'] for l in plan['legs']]}")

    for leg in plan["legs"]:
        print(f"[PLAN] leg: {leg['side']} qty={leg['qty']} {leg['symbol']} "
              f"ref_price={leg['ref_price']:.2f} ret_21d={leg['ret_21d']:.4f} "
              f"adv={leg['adv_inr']:,.0f} assumed_cost={leg['assumed_cost_inr']:.2f} INR "
              f"({cost_in_bps(leg['assumed_cost_inr'], leg['ref_price'], leg['qty']):.2f} bps)")

    session = {
        "schema_version": SCHEMA_VERSION,
        "event": "session",
        "utc_timestamp": now_utc_iso(),
        "rebalance_date": rebalance.isoformat(),
        "universe_size": len(UNIVERSE_49),
        "lookback_trading_days": LOOKBACK_TRADING_DAYS,
        "k": plan["k"],
        "k_requested": args.k,
        "budget_inr": args.budget,
        "dry_run": args.dry_run,
        "order_type": args.order_type,
        "is_amo": args.is_amo,
        "hypothesis_mode": mode2,
        "hypothesis": header2,
        "backtest_assumed_cost_params": BACKTEST_ASSUMED_COST_PARAMS,
        "sandbox_base_url": args.base_url,
    }

    # 3) Execute (or stop at the plan in dry-run)
    if args.dry_run:
        print("\n[DRY-RUN] No sandbox API calls made. The order payload below is what WOULD be sent:")
        for leg in plan["legs"]:
            print(json.dumps({
                "quantity": leg["qty"],
                "product": "D",
                "validity": "DAY",
                "price": float(args.limit_price or 0.0),
                "tag": f"alphacore-basket-{rebalance.isoformat()}",
                "instrument_token": instrument_keys[leg["symbol"]],
                "order_type": args.order_type,
                "transaction_type": leg["side"],
                "disclosed_quantity": 0,
                "trigger_price": 0.0,
                "is_amo": args.is_amo,
                "market_protection": -1,
                "_note": "instrument_token from Upstox instrument master (NSE_EQ|<ISIN>)",
            }, indent=2))
        records = [session]
    else:
        token = args.token or os.environ.get("UPSTOX_SANDBOX_TOKEN", "")
        if not token:
            print("[FATAL] UPSTOX_SANDBOX_TOKEN is required for live-sandbox mode "
                  "(generate from your Upstox sandbox app; see sandbox/README.md). "
                  "Use --dry-run to validate the pipeline without a token.", file=sys.stderr)
            raw.close()
            return 2
        if args.order_type == "LIMIT" and args.limit_price is None:
            print("[FATAL] --limit-price is required with --order-type LIMIT", file=sys.stderr)
            raw.close()
            return 2
        client = UpstoxSandboxClient(token, base_url=args.base_url, raw_logger=raw)
        records = [session]
        records += execute_rebalance(plan, client, raw, args.order_type, args.limit_price,
                                     args.is_amo, args.place_rotation_sells, instrument_keys)

    name = f"rebalance_{rebalance.isoformat()}.jsonl"
    write_jsonl(args.logs_dir, name, records)
    raw.close()
    print("\n[DONE] See raw API log + JSONL above for the verbatim sandbox responses.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
