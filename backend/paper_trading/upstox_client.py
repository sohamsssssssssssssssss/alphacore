"""Thin Upstox REST client for the paper-trading harness.

SANDBOX-ONLY POLICY — enforced twice:
  1. The order client is constructed only with the sandbox base URL
     (config.sandbox_url() raises if PAPER_SANDBOX_URL is not the sandbox host).
  2. Every order-mutating method re-asserts the host before sending.

Read-only market data (quotes / instruments / candles) runs against the LIVE
read-only API host — fetching quotes does not touch capital and is explicitly
allowed by the experiment design.

Uses `requests` (already in repo requirements.txt). All methods raise
UpstoxAPIError on non-2xx / malformed responses; callers handle failures.
"""

from __future__ import annotations

import time

import requests

from . import config


class UpstoxAPIError(RuntimeError):
    """Raised for HTTP errors / malformed sandbox responses."""


class OrderClient:
    """Order lifecycle against the SANDBOX host only."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or config.sandbox_url()).rstrip("/")
        if not self.base_url.startswith("https://sandbox.upstox.com"):
            raise RuntimeError(
                f"REFUSING TO CONSTRUCT order client for {self.base_url!r} — "
                f"not the Upstox sandbox host."
            )
        self._session = requests.Session()

    # ── guards ──────────────────────────────────────────────────────────────
    def _assert_sandbox(self, action: str) -> None:
        if not self.base_url.startswith("https://sandbox.upstox.com"):
            raise RuntimeError(
                f"REFUSING TO {action} — base URL {self.base_url!r} is not the "
                f"Upstox sandbox host. Sandbox-only policy."
            )

    def _post(self, path: str, token: str, payload: dict) -> dict:
        self._assert_sandbox("place/modify orders")
        resp = self._session.post(
            f"{self.base_url}{path}", json=payload,
            headers={"Accept": "application/json",
                     "Authorization": f"Bearer {token}"},
            timeout=30,
        )
        return self._check(resp, path)

    def _put(self, path: str, token: str, payload: dict) -> dict:
        self._assert_sandbox("modify orders")
        resp = self._session.put(
            f"{self.base_url}{path}", json=payload,
            headers={"Accept": "application/json",
                     "Authorization": f"Bearer {token}"},
            timeout=30,
        )
        return self._check(resp, path)

    def _delete(self, path: str, token: str) -> dict:
        self._assert_sandbox("cancel orders")
        resp = self._session.delete(
            f"{self.base_url}{path}",
            headers={"Accept": "application/json",
                     "Authorization": f"Bearer {token}"},
            timeout=30,
        )
        return self._check(resp, path)

    def _get(self, path: str, token: str) -> dict:
        self._assert_sandbox("read order data")
        resp = self._session.get(
            f"{self.base_url}{path}",
            headers={"Accept": "application/json",
                     "Authorization": f"Bearer {token}"},
            timeout=30,
        )
        return self._check(resp, path)

    @staticmethod
    def _check(resp: requests.Response, path: str) -> dict:
        try:
            body = resp.json()
        except ValueError:
            raise UpstoxAPIError(f"{path}: HTTP {resp.status_code}, non-JSON body")
        if resp.status_code >= 400 or body.get("status") == "error":
            detail = body.get("errors") or body.get("message") or body
            raise UpstoxAPIError(f"{path}: HTTP {resp.status_code} — {detail}")
        return body

    # ── order lifecycle (v2 endpoints, sandbox-enabled) ─────────────────────
    def place_order(self, token: str, *, instrument_token: str, quantity: int,
                    transaction_type: str, order_type: str = "MARKET",
                    product: str = "D", price: float = 0.0,
                    trigger_price: float = 0.0, tag: str = "",
                    validity: str = "DAY", is_amo: bool = False) -> dict:
        payload = {
            "quantity": int(quantity),
            "product": product,
            "validity": validity,
            "price": float(price),
            "instrument_token": instrument_token,
            "order_type": order_type,
            "transaction_type": transaction_type,
            "disclosed_quantity": 0,
            "trigger_price": float(trigger_price),
            "is_amo": is_amo,
            "market_protection": config.ORDER_MARKET_PROTECTION,
        }
        if tag:
            payload["tag"] = tag
        body = self._post("/v2/order/place", token, payload)
        data = body.get("data") or {}
        order_id = data.get("order_id")
        if not order_id and data.get("order_ids"):
            order_id = data["order_ids"][0]
        if not order_id:
            raise UpstoxAPIError(f"place_order: no order_id in response: {body}")
        return {"order_id": order_id, "raw": body}

    def get_order_book(self, token: str) -> dict:
        return self._get("/v2/order/book", token)

    def get_order_details(self, token: str, order_id: str) -> dict:
        return self._get(f"/v2/order/details/{order_id}", token)

    def get_order_history(self, token: str, order_id: str) -> dict:
        return self._get(f"/v2/order/history/{order_id}", token)

    def get_order_trades(self, token: str, order_id: str) -> dict:
        return self._get(f"/v2/order/trades/{order_id}", token)


class MarketDataClient:
    """Read-only market data against the LIVE API host (no order capabilities).

    Order-mutating methods are intentionally absent from this class; placing
    orders through this client is impossible by construction.
    """

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or config.marketdata_url()).rstrip("/")
        self._session = requests.Session()

    @staticmethod
    def _check(resp: requests.Response, path: str) -> dict:
        try:
            body = resp.json()
        except ValueError:
            raise UpstoxAPIError(f"{path}: HTTP {resp.status_code}, non-JSON body")
        if resp.status_code >= 400 or body.get("status") == "error":
            detail = body.get("errors") or body.get("message") or body
            raise UpstoxAPIError(f"{path}: HTTP {resp.status_code} — {detail}")
        return body

    def _get(self, path: str, token: str) -> dict:
        resp = self._session.get(
            f"{self.base_url}{path}",
            headers={"Accept": "application/json",
                     "Authorization": f"Bearer {token}"},
            timeout=30,
        )
        return self._check(resp, path)

    def quotes(self, token: str, instrument_keys: list[str]) -> dict:
        """LTP + OHLC + depth for up to 500 instrument keys (comma-separated)."""
        path = "/v2/market-quote/quotes?instrument_key=" + ",".join(instrument_keys)
        return self._get(path, token)

    def candles(self, token: str, instrument_key: str, interval: str = "1d",
                frm: str | None = None, to: str | None = None) -> dict:
        parts = [instrument_key, interval, frm or "", to or ""]
        return self._get("/v2/historical-candle/" + "/".join(parts), token)

    def instruments(self, token: str, exchange: str = "NSE_EQ") -> list[dict]:
        body = self._get(f"/v2/instruments/{exchange}", token)
        return body.get("data", [])

    def market_status(self, token: str) -> dict:
        return self._get("/v2/market/status", token)
