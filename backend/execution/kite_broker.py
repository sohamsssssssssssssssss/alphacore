from __future__ import annotations

import argparse
import logging
import os
from typing import Any

from kiteconnect import KiteConnect
from kiteconnect.exceptions import GeneralException, NetworkException

logger = logging.getLogger(__name__)


class KiteBroker:
    def __init__(self, api_key: str, access_token: str):
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(access_token)
        self._order_log: list[dict[str, Any]] = []

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        order_type: str,
        product: str,
        price: float = None,
        trigger_price: float = None,
    ) -> str:
        if not symbol or not symbol.strip():
            raise ValueError("symbol must be non-empty")
        if qty <= 0:
            raise ValueError("qty must be > 0")

        side_norm = side.upper()
        order_type_norm = order_type.upper()
        product_norm = product.upper()

        if side_norm not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if order_type_norm not in {"MARKET", "LIMIT", "SL", "SL-M"}:
            raise ValueError("order_type must be one of MARKET, LIMIT, SL, SL-M")
        if product_norm not in {"CNC", "MIS", "NRML"}:
            raise ValueError("product must be one of CNC, MIS, NRML")

        txn = (
            self.kite.TRANSACTION_TYPE_BUY
            if side_norm == "BUY"
            else self.kite.TRANSACTION_TYPE_SELL
        )

        params: dict[str, Any] = {
            "variety": self.kite.VARIETY_REGULAR,
            "exchange": self.kite.EXCHANGE_NSE,
            "tradingsymbol": symbol.strip().upper(),
            "transaction_type": txn,
            "quantity": int(qty),
            "order_type": order_type_norm,
            "product": product_norm,
        }
        if price is not None:
            params["price"] = float(price)
        if trigger_price is not None:
            params["trigger_price"] = float(trigger_price)

        try:
            order_id = self.kite.place_order(**params)
        except (NetworkException, GeneralException) as exc:
            logger.exception("Kite place_order failed for %s: %s", symbol, exc)
            raise

        record = {
            "order_id": str(order_id),
            "symbol": symbol.strip().upper(),
            "side": side_norm,
            "qty": int(qty),
            "order_type": order_type_norm,
            "product": product_norm,
            "price": price,
            "trigger_price": trigger_price,
        }
        self._order_log.append(record)
        return str(order_id)

    def get_positions(self) -> list[dict[str, Any]]:
        payload = self.kite.positions()
        net_positions = payload.get("net", []) if isinstance(payload, dict) else []
        out: list[dict[str, Any]] = []
        for p in net_positions:
            out.append(
                {
                    "symbol": p.get("tradingsymbol") or p.get("symbol") or "",
                    "qty": int(p.get("quantity", 0) or 0),
                    "avg_price": float(p.get("average_price", 0.0) or 0.0),
                    "pnl": float(p.get("pnl", 0.0) or 0.0),
                    "product": p.get("product") or "",
                }
            )
        return out

    def cancel_order(self, order_id: str, variety: str = "regular") -> bool:
        try:
            self.kite.cancel_order(variety=variety, order_id=order_id)
            return True
        except Exception:
            logger.exception("Kite cancel_order failed for order_id=%s", order_id)
            return False

    def get_order_status(self, order_id: str) -> str:
        history = self.kite.order_history(order_id)
        if not history:
            return "OPEN"
        status = str(history[-1].get("status", "OPEN")).upper()
        if status in {"OPEN", "COMPLETE", "REJECTED", "CANCELLED"}:
            return status
        return "OPEN"


def _run_test_connection() -> None:
    api_key = os.getenv("API_KEY", "")
    access_token = os.getenv("ACCESS_TOKEN", "")
    if not api_key or not access_token:
        raise RuntimeError("API_KEY and ACCESS_TOKEN env vars are required")

    broker = KiteBroker(api_key=api_key, access_token=access_token)
    positions = broker.get_positions()
    print(f"KiteConnect initialized. Fetched {len(positions)} current positions.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-connection", action="store_true")
    args = parser.parse_args()

    if args.test_connection:
        _run_test_connection()


if __name__ == "__main__":
    main()
