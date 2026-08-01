"""Paper-trading scheduler: the unattended main loop.

Cycle responsibilities (in order):
  1. kill-switch check + token hot-reload
  2. market-open check (read-only status API, throttled)
  3. rebalance window (15:10–15:29 IST) on rebalance days → signal → orders →
     fill polling → slippage recording
  4. close capture (~15:32 IST) → signal close series + daily MTM
  5. reconciliation of orders left pending by crashes/restarts

Failure policy: no individual failure crashes the loop — it is logged with
context and retried on the next cycle. Repeated failures are throttled so the
log stays readable over a multi-month run.
"""

from __future__ import annotations

import json
import signal
import sys
import time
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paper_trading import config, costs  # noqa: E402
from paper_trading.events import EventLog  # noqa: E402
from paper_trading.instruments import InstrumentCache  # noqa: E402
from paper_trading.ledger import Ledger  # noqa: E402
from paper_trading.market_data import (CloseHistory, QuoteCache,  # noqa: E402
                                       MIN_CAPTURE_COUNT, midpoint)
from paper_trading.strategy import Strategy  # noqa: E402
from paper_trading.token_store import TokenStore  # noqa: E402
from paper_trading.upstox_client import MarketDataClient, OrderClient  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")

TERMINAL_STATUSES = {"complete", "cancelled", "rejected", "expired"}


def _now() -> datetime:
    return datetime.now(IST)


def _today() -> str:
    return _now().date().isoformat()


class PaperScheduler:
    def __init__(self, symbols: list[str], dry_run: bool = False):
        self.symbols = sorted(symbols)
        self.dry_run = dry_run
        self.log = EventLog()
        self.tokens = TokenStore()
        self.ledger = Ledger()
        self.history = CloseHistory()
        self.strategy = Strategy(symbols)
        self.md_client = MarketDataClient()
        self.order_client = None if dry_run else OrderClient()
        self.instruments = InstrumentCache(symbols)
        self.quote_cache: QuoteCache | None = None
        self._last_alert: dict[str, float] = {}
        self._last_market_status_check = 0.0
        self._market_open = False
        self._kill_requested = False
        self._boots = 0

        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)

    # ── lifecycle ───────────────────────────────────────────────────────────
    def _on_signal(self, signum, frame):  # noqa: ARG002
        self.log.shutdown({"reason": f"signal {signum}", "graceful": True})
        self._kill_requested = True

    def _kill_check(self) -> bool:
        if self._kill_requested:
            return True
        try:
            if config.KILL_FILE.exists():
                self.log.kill_detected({"file": str(config.KILL_FILE)})
                return True
        except OSError:
            pass
        return False

    def _alert_throttled(self, key: str, message: str, every: float = 3600.0) -> None:
        last = self._last_alert.get(key, 0.0)
        if time.time() - last >= every:
            self._last_alert[key] = time.time()
            config.slack_notify(message)

    def _boot(self) -> None:
        self.ledger.load()
        if not self.history.load():
            n = self.history.seed_from_csv(self.symbols)
            self.log.boot({"seeded_from_csv": n, "symbols": len(self.symbols),
                           "seed_date": self.history.seed_date})
        else:
            self.log.boot({"restored": True, "symbols": len(self.symbols),
                           "latest_date": self.history.latest_date()})
        self._boots = self.ledger.data.get("boots", 0) + 1
        self.ledger.data["boots"] = self._boots
        self.ledger.save()
        self.log.log("boot", {"boot_count": self._boots, "dry_run": self.dry_run,
                              "base_url": config.sandbox_url()})

    def run(self) -> None:
        self._boot()
        while not self._kill_check():
            try:
                self.cycle()
            except Exception as exc:  # noqa: BLE001
                self.log.error({"msg": "cycle failed", "exc": repr(exc)})
                self._alert_throttled("cycle_error", f"paper cycle error: {exc}")
                time.sleep(config.LOOP_SLEEP_OFFHOURS)
                continue
            interval = (config.LOOP_SLEEP_TRADING if self._market_open
                        else config.LOOP_SLEEP_OFFHOURS)
            # sleep in small chunks so the kill switch is honored promptly
            slept = 0
            while slept < interval and not self._kill_check():
                time.sleep(min(5, interval - slept))
                slept += 5
        self.log.shutdown({"reason": "kill switch or signal", "graceful": True})

    # ── cycle ───────────────────────────────────────────────────────────────
    def cycle(self) -> None:
        self.tokens.reload_if_changed()
        tok = self.tokens.tokens

        if not tok.sandbox_ok():
            self.log.auth_expired({
                "token_set": bool(tok.sandbox_token),
                "expired": not tok.sandbox_ok(),
                "action": "orders suppressed until a valid sandbox token is provided",
            })
            self._alert_throttled(
                "auth_expired",
                "ALPHACORE PAPER: sandbox token missing/expired — orders suppressed. "
                "Regenerate at account.upstox.com/developer/apps#sandbox and update "
                "backend/paper_trading/.env or states/paper_trading/tokens.json.",
                every=6 * 3600.0)
            return

        self._refresh_instruments(tok)

        if self.dry_run:
            return

        now = _now()
        self._refresh_market_status(tok)

        # ── rebalance window ──
        in_window = dtime(15, 10) <= now.time() <= dtime(15, 29)
        if in_window and self._market_open:
            self._maybe_rebalance(tok, now.date().isoformat())

        # ── close capture ──
        if now.time() >= time(15, 32) and now.time() < time(16, 30) and self._market_open:
            self._capture_closes(tok)

        # ── reconcile pending orders ──
        self._reconcile_pending(tok)

    # ── helpers ─────────────────────────────────────────────────────────────
    def _refresh_market_status(self, tok) -> None:
        if time.time() - self._last_market_status_check < 600:
            return
        self._last_market_status_check = time.time()
        try:
            body = self.md_client.market_status(tok.sandbox_token)
            data = body.get("data") or {}
            nse = (data.get("exchange") or {}).get("NSE") or {}
            status = str(nse.get("status", "")).lower()
            self._market_open = status == "open"
        except Exception as exc:  # noqa: BLE001
            self.log.market_data_error({"msg": "market status unavailable",
                                        "exc": repr(exc)})
            self._market_open = False

    def _refresh_instruments(self, tok) -> None:
        if self.quote_cache is not None:
            return
        inst_map, source = self.instruments.ensure(self.md_client, self.tokens)
        if "static_fallback" in source or "missing" in source:
            self.log.instrument_fallback({"source": source})
        self.quote_cache = QuoteCache(self.md_client, inst_map)

    # ── rebalance ───────────────────────────────────────────────────────────
    def _maybe_rebalance(self, tok, today: str) -> None:
        if self.ledger.data.get("rebalance_done_for_date") == today:
            return
        last = self.ledger.data.get("last_rebalance_date")
        if not self.strategy.is_rebalance_day(self.history, last):
            return
        self.log.rebalance_start({
            "date": today,
            "last_rebalance_date": last,
            "days_since": self.history.count_trading_days_since(last),
            "equity": self.ledger.equity,
        })
        if self.order_client is None:
            self.log.rebalance_complete({"mode": "dry_run", "date": today})
            return
        self._execute_rebalance(tok, today)

    def _execute_rebalance(self, tok, today: str) -> None:
        quotes, failed = self.quote_cache.fetch(tok.sandbox_token)
        if failed:
            self.log.market_data_error({"msg": "quotes failed for rebalance",
                                        "symbols": failed})
        plan = self.strategy.plan_rebalance(
            self.history, self.ledger.equity, self.ledger.positions, quotes)
        self.log.log("rebalance", {"plan": plan})

        closed_ok: list[str] = []
        for order in plan.get("closes", []):
            ok = self._execute_order(tok, order, quotes, closing=True)
            if ok:
                closed_ok.append(order["symbol"])
                self.ledger.set_position(order["symbol"], None)

        for order in plan.get("opens", []):
            if order["symbol"] in closed_ok:
                continue  # position carried forward unresolved; no double book
            ok = self._execute_order(tok, order, quotes, closing=False)
            if ok:
                self.ledger.set_position(order["symbol"], {
                    "leg": order["leg"],
                    "qty": order["qty"],
                    "entry_price": quotes.get(order["symbol"], {}).get("last"),
                    "entry_date": today,
                    "entry_order_id": ok,
                    "last_mark": quotes.get(order["symbol"], {}).get("last"),
                })

        self.ledger.data["last_rebalance_date"] = today
        self.ledger.data["rebalance_count"] = int(
            self.ledger.data.get("rebalance_count", 0)) + 1
        self.ledger.data["rebalance_done_for_date"] = today
        self.ledger.save()
        self.log.rebalance_complete({"date": today, "closed_ok": closed_ok,
                                     "opens_submitted": len(plan.get("opens", []))})

    def _execute_order(self, tok, order: dict, quotes: dict,
                       closing: bool) -> str | None:
        """Place one order, poll to terminal state, record the trade.

        Returns order_id on success (terminal complete), None otherwise.
        """
        sym = order["symbol"]
        quote = quotes.get(sym, {})
        ref_mid = midpoint(quote)
        key = self.quote_cache.instrument_map.get(sym, "")
        if not key:
            self.log.error({"msg": "no instrument key", "symbol": sym})
            return None

        product = (config.ORDER_PRODUCT_LONG if order["leg"] == "LONG"
                   else config.ORDER_PRODUCT_SHORT)
        order["product"] = product
        try:
            resp = self.order_client.place_order(
                tok.sandbox_token, instrument_token=key, quantity=order["qty"],
                transaction_type=order["side"], order_type=config.ORDER_TYPE,
                product=product, tag=config.ORDER_TAG,
                validity=config.ORDER_VALIDITY)
        except Exception as exc:  # noqa: BLE001
            self.log.order_terminal({
                "symbol": sym, "leg": order["leg"], "side": order["side"],
                "qty": order["qty"], "status": "rejected_at_placement",
                "error": repr(exc)})
            return None
        order_id = resp["order_id"]
        self.log.order_submitted({
            "order_id": order_id, "symbol": sym, "leg": order["leg"],
            "side": order["side"], "qty": order["qty"], "product": product,
            "instrument_token": key, "ref_mid": ref_mid,
            "closing": closing, "submitted_at": _now().isoformat(),
        })

        terminal = self._poll_order(tok, order_id)
        if terminal.get("status") != "complete":
            self.log.log("order_terminal", {
                "order_id": order_id, "symbol": sym, "leg": order["leg"],
                "side": order["side"], "status": terminal.get("status"),
                "message": terminal.get("status_message"),
                "resolved": terminal.get("resolved", False)})
            if not terminal.get("resolved"):
                self._add_pending(order_id, sym, order, ref_mid)
            return None

        self._record_trade(order_id, order, quote, ref_mid, terminal)
        return order_id

    def _poll_order(self, tok, order_id: str) -> dict:
        deadline = time.time() + config.fill_poll_timeout()
        while time.time() < deadline:
            try:
                body = self.order_client.get_order_details(tok.sandbox_token, order_id)
                data = body.get("data") or {}
                status = str(data.get("status", "")).lower()
                self.log.order_poll({"order_id": order_id, "status": status,
                                     "filled": data.get("filled_quantity")})
                if status in TERMINAL_STATUSES:
                    data["resolved"] = True
                    return data
            except Exception as exc:  # noqa: BLE001
                self.log.order_poll({"order_id": order_id, "error": repr(exc)})
            time.sleep(config.FILL_POLL_INTERVAL)
        return {"status": "unknown", "resolved": False, "order_id": order_id}

    def _record_trade(self, order_id: str, order: dict, quote: dict,
                      ref_mid: float | None, terminal: dict) -> None:
        sym = order["symbol"]
        fill_price = _num(terminal.get("average_price"))
        filled_qty = int(terminal.get("filled_quantity") or 0)
        fill_source = "sandbox"
        if fill_price is None or filled_qty <= 0:
            # fallback: live quote (ask for buys, bid for sells) — flagged
            if ref_mid and quote.get("last"):
                fill_price = (quote.get("ask") if order["side"] == "BUY"
                              else quote.get("bid")) or quote.get("last")
                fill_source = "live_quote_fallback"
                filled_qty = order["qty"]
            else:
                fill_price = 0.0
        if fill_price <= 0:
            self.log.log("order_terminal", {"order_id": order_id, "symbol": sym,
                                            "status": "no_fill_price"})
            return

        spread_bps = costs.spread_bps(quote.get("bid"), quote.get("ask"),
                                      ref_mid or quote.get("last"))
        slippage_bps = (costs.realized_slippage_bps(fill_price, ref_mid, order["side"])
                        if ref_mid else None)
        slippage_rs = (costs.realized_slippage_rs(fill_price, ref_mid,
                                                  order["side"], filled_qty)
                       if ref_mid else None)
        modeled_rs = costs.modeled_cost_rs(fill_price, filled_qty, spread_bps,
                                           order["side"])

        trade = {
            "order_id": order_id, "symbol": sym, "leg": order["leg"],
            "side": order["side"], "qty": filled_qty, "product": order.get("product"),
            "fill_price": fill_price, "fill_source": fill_source,
            "ref_mid": ref_mid, "spread_bps_live": spread_bps,
            "slippage_bps": slippage_bps, "slippage_rs": slippage_rs,
            "modeled_cost_rs": modeled_rs,
            "status": terminal.get("status"),
            "filled_at": _now().isoformat(),
        }
        self.log.trade(trade)

        if ref_mid and abs(fill_price - ref_mid) / ref_mid > config.fill_sanity_max_deviation():
            self.log.fill_sanity_fail({"order_id": order_id, "symbol": sym,
                                       "fill": fill_price, "ref_mid": ref_mid})
            self._alert_throttled(
                "fill_sanity", f"ALPHACORE PAPER: suspect sandbox fill {sym} "
                f"fill={fill_price} mid={ref_mid} — see PAPER_TRADING_LOG.md")

    def _add_pending(self, order_id: str, sym: str, order: dict, ref_mid) -> None:
        pend = self.ledger.data.setdefault("pending_orders", [])
        pend.append({"order_id": order_id, "symbol": sym, "leg": order["leg"],
                     "side": order["side"], "qty": order["qty"],
                     "ref_mid": ref_mid, "added_at": _now().isoformat()})
        self.ledger.save()

    def _reconcile_pending(self, tok) -> None:
        pend = self.ledger.data.get("pending_orders", [])
        if not pend:
            return
        remaining = []
        for entry in pend:
            terminal = self._poll_order(tok, entry["order_id"])
            if terminal.get("status") in TERMINAL_STATUSES or terminal.get("resolved"):
                if terminal.get("status") == "complete":
                    self._record_trade(entry["order_id"], entry, {},
                                       entry.get("ref_mid"), terminal)
                self.log.log("order_terminal", {
                    "order_id": entry["order_id"], "symbol": entry["symbol"],
                    "status": terminal.get("status"), "reconciled": True})
            else:
                remaining.append(entry)
        self.ledger.data["pending_orders"] = remaining
        self.ledger.save()

    # ── close capture / MTM ─────────────────────────────────────────────────
    def _capture_closes(self, tok) -> None:
        today = _today()
        if self.ledger.data.get("last_close_capture_date") == today:
            return
        quotes, failed = self.quote_cache.fetch(tok.sandbox_token)
        closes = {sym: q.get("close") or q.get("last")
                  for sym, q in quotes.items() if q.get("last")}
        n = self.history.append_day(today, closes)
        if n < MIN_CAPTURE_COUNT:
            self.log.close_capture({"date": today, "captured": n,
                                    "failed": failed,
                                    "note": "below threshold; not a trading day"})
            return
        self.ledger.data["last_close_capture_date"] = today
        self._mark_to_market(today, quotes)
        self.ledger.save()
        self.log.close_capture({"date": today, "captured": n,
                                "failed": failed, "equity": self.ledger.equity})

    def _mark_to_market(self, date: str, quotes: dict) -> None:
        equity = self.ledger.equity
        for sym, pos in list(self.ledger.positions.items()):
            q = quotes.get(sym)
            mark = q.get("close") or q.get("last") if q else None
            if not mark:
                continue
            last_mark = pos.get("last_mark") or pos.get("entry_price")
            if not last_mark:
                continue
            if pos["leg"] == "LONG":
                equity += (mark - last_mark) * pos["qty"]
            else:
                equity += (last_mark - mark) * pos["qty"]
            pos["last_mark"] = mark
        self.ledger.equity = equity
        self.ledger.mark_daily(date, equity)
        self.log.daily_mtm({"date": date, "equity": equity,
                            "positions": len(self.ledger.positions)})


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="AlphaCore paper-trading scheduler")
    parser.add_argument("--dry-run", action="store_true",
                        help="signal + plan only; no orders, no network")
    parser.add_argument("--state-dir", default=None, help="override state dir")
    args = parser.parse_args()

    if args.state_dir:
        config.STATE_DIR = Path(args.state_dir)
        config.LOG_FILE = config.STATE_DIR / "logs" / "events.jsonl"
        config.TOKENS_FILE = config.STATE_DIR / "tokens.json"
        config.STATE_FILE = config.STATE_DIR / "state.json"
        config.INSTRUMENTS_FILE = config.STATE_DIR / "instruments.json"
        config.CLOSE_HISTORY_FILE = config.STATE_DIR / "close_history.json"
        config.KILL_FILE = config.STATE_DIR / "KILL"

    symbols = sorted(p.stem for p in config.DATA_DIR_50.glob("*.csv"))
    if not symbols:
        print("ERROR: no symbol CSVs found in backend/data/nifty50_data")
        sys.exit(1)
    print(f"AlphaCore paper scheduler — {len(symbols)} symbols "
          f"(dry_run={args.dry_run})")
    PaperScheduler(symbols, dry_run=args.dry_run).run()


if __name__ == "__main__":
    main()
