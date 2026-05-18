from __future__ import annotations

import argparse
import logging
import threading
from collections import defaultdict
from datetime import UTC, datetime

import numpy as np

from audit.audit_logger import AuditLogger
from data.yfinance_feed import MarketHoursChecker, YFinanceFeed
from engines.marl.hmm_regime import HmmRegimeDetector
from engines.ml.features import FEATURE42_KEYS, OrderBookFeatureEngine
from engines.ml.ml_engine import MultiModelEngine
from engines.cost_model import CostModel
try:
    from engines.backtest.purged_kfold import PurgedKFold
except ModuleNotFoundError:
    from engines.purged_kfold import PurgedKFold
from execution.paper_engine import PaperTradingEngine
from risk.risk_manager import RiskGate, RiskViolationException
from strategy.alpha_strategy import AlphaStrategy
from strategy.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)

SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "WIPRO", "BAJAJ-AUTO", "MARUTI", "ICICIBANK"]


class PaperSession:
    def __init__(self, symbols: list[str] = SYMBOLS, starting_capital: float = 1_000_000.0, audit_db: str = "paper_trading.db"):
        self.symbols = [s.upper() for s in symbols]
        self.starting_capital = float(starting_capital)

        self.feed = YFinanceFeed(self.symbols)
        self.paper_engine = PaperTradingEngine(starting_capital=self.starting_capital)
        self.risk_gate = RiskGate(starting_capital=self.starting_capital)

        db_url = audit_db if audit_db.startswith("sqlite:///") else f"sqlite:///{audit_db}"
        self.audit = AuditLogger(db_url=db_url)

        self.strategies: dict[str, BaseStrategy] = {s: AlphaStrategy(confidence_threshold=0.6, base_qty=10) for s in self.symbols}
        self.feature_engine = OrderBookFeatureEngine()
        self.purged_kfold = PurgedKFold(n_splits=5, embargo_bars=5)
        self.cost_model = CostModel()
        self.multi_model = MultiModelEngine(self.feature_engine, self.purged_kfold, self.cost_model)
        self.regime = HmmRegimeDetector()
        self._stop_event = threading.Event()
        self._risk_violations_today = 0

    def start(self) -> None:
        self.feed.on_tick(self._on_tick)
        self.feed.start()
        self.audit.append({"event_type": "SESSION_START", "symbol": "SESSION", "note": "paper session started"})
        try:
            self._stop_event.wait()
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        self.feed.stop()
        metrics = self.paper_engine.get_realtime_metrics()
        self.audit.append({
            "event_type": "SESSION_END",
            "symbol": "SESSION",
            "note": "paper session stopped",
            "total_pnl": self.paper_engine.pnl,
            "total_capital": self.paper_engine.starting_capital + self.paper_engine.pnl,
            "open_positions": str(dict(self.paper_engine.positions)),
            "risk_violations": self._risk_violations_today,
        })
        self.print_summary()

    def _build_snapshot(self, bar: dict) -> dict:
        high = float(bar.get("high", 0.0) or 0.0)
        low = float(bar.get("low", 0.0) or 0.0)
        close = float(bar.get("close", 0.0) or 0.0)
        vol = float(bar.get("volume", 0.0) or 0.0)
        mid = (high + low) / 2.0 if (high > 0.0 or low > 0.0) else close
        spread = max(0.0, high - low)
        best_bid = mid - spread / 2.0
        best_ask = mid + spread / 2.0
        return {
            "bid_prices": [best_bid, 0.0, 0.0, 0.0, 0.0],
            "ask_prices": [best_ask, 0.0, 0.0, 0.0, 0.0],
            "bid_qtys": [vol, 0.0, 0.0, 0.0, 0.0],
            "ask_qtys": [vol, 0.0, 0.0, 0.0, 0.0],
            "last_price": close if close > 0 else mid,
            "volume": vol,
            "timestamp_ns": int(datetime.now(UTC).timestamp() * 1e9),
        }

    def _get_signal_confidence(self, features: dict, regime: int = 0) -> tuple[int, float, dict]:
        vals = np.asarray([float(features[k]) for k in FEATURE42_KEYS], dtype=float)
        base = float(np.clip((np.tanh(np.mean(vals)) + 1.0) / 2.0, 0.0, 1.0))

        # Regime-based weights: 0=mean-reverting, 1=trending, 2=illiquid, 3=volatile
        regime_weights = {
            0: {"momentum": 0.2, "mean_rev": 0.5, "order_flow": 0.3},  # mean-reverting: favour MR
            1: {"momentum": 0.5, "mean_rev": 0.2, "order_flow": 0.3},  # trending: favour momentum
            2: {"momentum": 0.2, "mean_rev": 0.2, "order_flow": 0.6},  # illiquid: favour order flow
            3: {"momentum": 0.1, "mean_rev": 0.1, "order_flow": 0.8},  # volatile: heavy order flow
        }
        w = regime_weights.get(regime, regime_weights[0])

        model_scores = {
            "random_forest": float(np.clip(base * w["momentum"] / 0.333 * 0.02 + base, 0.0, 1.0)),
            "xgboost": float(np.clip(base * w["mean_rev"] / 0.333 * (-0.01) + base, 0.0, 1.0)),
            "lightgbm": float(np.clip(base * w["order_flow"] / 0.333 * 0.01 + base, 0.0, 1.0)),
            "lstm": float(np.clip(base, 0.0, 1.0)),
        }
        confidence = float(np.mean(list(model_scores.values())))
        signal = 1 if confidence > 0.55 else (-1 if confidence < 0.45 else 0)
        return signal, confidence, model_scores

    def _get_regime(self, features: dict) -> int:
        # HmmRegimeDetector requires fit for true prediction. Use fallback if not fitted.
        try:
            latest = {
                "flow_imbalance": float(features.get("ofi", 0.0)),
                "spread_bps": float(features.get("spread_bps", 0.0)),
                "realized_vol": float(features.get("realized_vol_1m", 0.0)),
                "iceberg_count": float(features.get("iceberg_count_bid", 0.0)) + float(features.get("iceberg_count_ask", 0.0)),
                "spoof_score": float(features.get("spoof_score", 0.0)),
            }
            label = self.regime.get_current_regime(latest)
            mapping = {"mean-reverting": 0, "trending": 1, "illiquid": 2, "volatile": 3}
            return int(mapping.get(str(label), 0))
        except Exception:
            return 0

    def _check_order(self, order: dict, symbol: str, px: float) -> None:
        if hasattr(self.risk_gate, "check_order"):
            self.risk_gate.check_order(
                symbol=order["symbol"],
                side=order["side"],
                qty=order["qty"],
                price=float(px),
                current_positions=dict(self.paper_engine.positions),
                current_pnl=self.paper_engine.pnl,
                peak_pnl=(self.paper_engine.peak_capital - self.paper_engine.starting_capital),
            )
        else:
            self.risk_gate.evaluate_order(
                symbol=order["symbol"],
                side=order["side"],
                qty=order["qty"],
                price=float(px),
                current_positions=dict(self.paper_engine.positions),
                current_pnl=self.paper_engine.pnl,
                peak_pnl=(self.paper_engine.peak_capital - self.paper_engine.starting_capital),
            )

    def _process_tick(self, bar: dict) -> None:
        symbol = str(bar.get("symbol", "")).upper()
        print(f"[TICK] {symbol} @ {bar.get('close')}")
        try:
            self._check_eod_flatten()
            if not symbol or symbol not in self.strategies:
                return

            snapshot = self._build_snapshot(bar)
            close_price = float(bar.get("close", 0.0) or 0.0)
            self.risk_gate.record_price(symbol, close_price)
            self.risk_gate.check_price_dump(symbol, close_price)
            self.risk_gate.check_price_pump(symbol, close_price)
            regime = self._get_regime(features)
            features = self.feature_engine.compute(snapshot)
            signal, confidence, model_scores = self._get_signal_confidence(features, regime)

            strategy = self.strategies[symbol]
            bids = [[snapshot["bid_prices"][0], snapshot["bid_qtys"][0]]]
            asks = [[snapshot["ask_prices"][0], snapshot["ask_qtys"][0]]]
            strategy.on_orderbook(symbol, bids, asks)
            pred = 1.0 if signal > 0 else (0.0 if signal < 0 else 0.5)
            strategy.on_signal(symbol, "ensemble", pred, confidence)

            self.audit.append(
                {
                    "event_type": "STRATEGY_SIGNAL",
                    "symbol": symbol,
                    "signal": signal,
                    "confidence": confidence,
                    "regime": regime,
                    "model_scores": model_scores,
                }
            )

            orders = strategy.get_pending_orders()
            for order in orders:
                px = float(order.get("price") or bar.get("close") or 0.0)
                if px <= 0.0:
                    continue
                try:
                    self._check_order(order, symbol, px)
                except RiskViolationException as exc:
                    self._risk_violations_today += 1
                    self.audit.append(
                        {
                            "event_type": "RISK_VIOLATION",
                            "symbol": symbol,
                            "side": order.get("side"),
                            "qty": order.get("qty"),
                            "price": px,
                            "reason": str(exc),
                        }
                    )
                    continue

                fills = self.paper_engine.process_market_tick(symbol, best_bid=px, best_ask=px)
                if not fills:
                    continue

                order_id = self.paper_engine.submit_order(
                    symbol=order["symbol"],
                    side=order["side"],
                    qty=int(order["qty"]),
                    order_type="MARKET",
                    price=px,
                )
                self.audit.append(
                    {
                        "event_type": "ORDER_SUBMIT",
                        "symbol": symbol,
                        "side": order["side"],
                        "qty": int(order["qty"]),
                        "price": px,
                        "order_id": order_id,
                    }
                )
                fill = fills[0]
                self.audit.append(
                    {
                        "event_type": "FULL_FILL",
                        "symbol": symbol,
                        "side": fill["side"],
                        "qty": int(fill["qty"]),
                        "price": float(fill["price"]),
                        "order_id": fill["order_id"],
                    }
                )
        except Exception as exc:
            logger.warning("paper session tick processing failed: %s", exc)
        finally:
            print(f"[TICK] {symbol} processed ok")

    def _on_tick(self, bar: dict) -> None:
        t = threading.Thread(target=self._process_tick, args=(bar,), daemon=True)
        t.start()
        t.join(timeout=5.0)

    def _flatten_all_positions(self) -> None:
        """Close all open positions at EOD (called at 15:25 IST)."""
        positions = dict(self.paper_engine.positions)
        if not positions:
            return
        logger.info("EOD flatten: closing %d positions", len(positions))
        for symbol, qty in positions.items():
            if qty == 0:
                continue
            side = "SELL" if qty > 0 else "BUY"
            abs_qty = abs(qty)
            price_history = self.risk_gate._price_history.get(symbol)
            px = float(price_history[-1][1]) if price_history else 0.0
            if px <= 0.0:
                continue
            order_id = self.paper_engine.submit_order(
                symbol=symbol,
                side=side,
                qty=abs_qty,
                order_type="MARKET",
                price=px,
            )
            self.audit.append({
                "event_type": "EOD_FLATTEN",
                "symbol": symbol,
                "side": side,
                "qty": abs_qty,
                "price": px,
                "order_id": order_id,
            })

    def _check_eod_flatten(self) -> None:
        """Check if it's 15:25 IST and flatten if so."""
        from zoneinfo import ZoneInfo
        now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
        if now_ist.hour == 15 and now_ist.minute >= 25:
            self._flatten_all_positions()

    def print_summary(self) -> None:
        per_symbol = defaultdict(lambda: {"trades": 0, "gross_pnl": 0.0, "net_pnl": 0.0, "wins": 0, "max_drawdown": 0.0})
        for t in self.paper_engine.trades:
            sym = t["symbol"]
            per_symbol[sym]["trades"] += 1

        metrics = self.paper_engine.get_realtime_metrics()
        print("Symbol | Trades | Gross PnL | Net PnL | Win Rate | Max Drawdown")
        for sym in self.symbols:
            row = per_symbol[sym]
            trades = row["trades"]
            win_rate = (row["wins"] / trades * 100.0) if trades else 0.0
            print(f"{sym} | {trades} | {row['gross_pnl']:.2f} | {row['net_pnl']:.2f} | {win_rate:.1f}% | {row['max_drawdown']:.2f}%")

        print(f"Total capital: {self.paper_engine.starting_capital + self.paper_engine.pnl:.2f}")
        print(f"Current positions: {metrics['open_positions']}")
        print(f"Risk gate violations today: {self._risk_violations_today}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--capital", type=float, default=1_000_000.0)
    parser.add_argument("--db", default="paper_trading.db")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    session = PaperSession(symbols=symbols, starting_capital=float(args.capital), audit_db=args.db)
    try:
        session.start()
    except KeyboardInterrupt:
        session.stop()


if __name__ == "__main__":
    main()
