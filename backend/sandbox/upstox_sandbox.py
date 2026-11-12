"""
Raw Upstox SANDBOX API client.

  * Base URL: https://api-sandbox.upstox.com  (verified from the official
    upstox-python SDK: Configuration(sandbox=True) sets host/order_host to
    https://api-sandbox.upstox.com — the web-doc claim of
    "sandbox.upstox.com" is wrong).
  * Auth: a dedicated SANDBOX access token (generated in the Upstox developer
    console for a sandbox app, valid 30 days). NEVER a live OAuth token.
  * Sandbox-enabled endpoints (per the SDK's sandbox_urls set and the Upstox
    docs): POST /v2/order/place, /v2/order/modify, /v2/order/cancel,
    /v2/order/multi/place and the /v3 equivalents. Order-history, trades,
    quotes and master-contract are NOT sandbox-enabled yet — the client still
    ATTEMPTS them and logs the raw API response verbatim (they typically
    return a 'not enabled for sandbox' style error), so the user can see
    exactly what the sandbox returns instead of us inventing fills.

Every request/response pair is written to the raw log AND printed to
stdout so the user can verify against terminal output (deliverable #4).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

import requests

logger = logging.getLogger(__name__)

SANDBOX_BASE_URL = "https://api-sandbox.upstox.com"
PLACE_ORDER_PATH = "/v2/order/place"
ORDER_HISTORY_PATH = "/v2/order/history"
ORDER_TRADES_PATH = "/v2/order/trades"
PROFILE_PATH = "/v2/user/profile"

MAX_RESPONSE_LOG_CHARS = 8000


class RawApiLogger:
    """Append-only verbatim log of every HTTP request/response against the sandbox."""

    def __init__(self, log_dir: str, session_tag: str = ""):
        os.makedirs(log_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{session_tag}" if session_tag else ""
        self.path = os.path.join(log_dir, f"raw_api_{stamp}{suffix}.txt")
        self._fh = open(self.path, "a", encoding="utf-8")
        self._seq = 0
        self._write(f"# Upstox SANDBOX raw API log — started {datetime.now().isoformat()}")

    def _write(self, text: str) -> None:
        self._fh.write(text + "\n")
        self._fh.flush()

    def log(self, method: str, url: str, request_headers: dict, body: Any, status: int | None,
            response_headers: dict | None, response_text: str, error: str | None = None) -> None:
        self._seq += 1
        block = [f"\n{'=' * 78}", f"===== [{self._seq}] {method} {url} =====", "REQUEST HEADERS:"]
        for k, v in (request_headers or {}).items():
            block.append(f"  {k}: {v}")
        block.append(f"REQUEST BODY: {json.dumps(body) if body is not None else '<none>'}")
        if error is not None:
            block.append(f"TRANSPORT ERROR: {error}")
        block.append(f"RESPONSE STATUS: {status if status is not None else '<none>'}")
        if response_headers:
            block.append("RESPONSE HEADERS:")
            for k, v in list(response_headers.items())[:25]:
                block.append(f"  {k}: {v}")
        shown = response_text or "<empty body>"
        if len(shown) > MAX_RESPONSE_LOG_CHARS:
            shown = shown[:MAX_RESPONSE_LOG_CHARS] + "\n... [truncated]"
        block.append("RESPONSE BODY:")
        block.append(shown)
        block.append("=" * 78)
        text = "\n".join(block)
        self._write(text)
        print(text)

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


class UpstoxSandboxClient:
    def __init__(self, access_token: str, base_url: str = SANDBOX_BASE_URL, raw_logger: RawApiLogger | None = None):
        if not access_token or not access_token.strip():
            raise ValueError("UPSTOX_SANDBOX_TOKEN is required (generate it from your sandbox app in the Upstox developer console)")
        self.access_token = access_token.strip()
        self.base_url = base_url.rstrip("/")
        self.raw = raw_logger

    # -- internals ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

    def _redacted_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer <REDACTED>"}

    def _request(self, method: str, path: str, body: dict | None = None,
                 params: dict | None = None) -> tuple[int, dict | str, str]:
        url = f"{self.base_url}{path}"
        try:
            resp = requests.request(method, url, json=body, params=params, headers=self._headers(), timeout=30)
            try:
                payload: dict | str = resp.json()
            except ValueError:
                payload = resp.text
            text = resp.text if isinstance(payload, str) else json.dumps(payload, indent=2, ensure_ascii=False)
            if self.raw is not None:
                self.raw.log(method, url, self._redacted_headers(), body,
                             resp.status_code, dict(resp.headers), text)
            return resp.status_code, payload, text
        except requests.RequestException as exc:
            if self.raw is not None:
                self.raw.log(method, url, self._redacted_headers(), body,
                             None, None, "", error=str(exc))
            raise

    # -- sandbox order APIs -------------------------------------------------

    def place_order(self, *, quantity: int, instrument_token: str, transaction_type: str,
                    order_type: str = "MARKET", product: str = "D", validity: str = "DAY",
                    price: float = 0.0, trigger_price: float = 0.0,
                    disclosed_quantity: int = 0, is_amo: bool = False,
                    market_protection: int = -1, tag: str = "alphacore-sandbox-k1") -> dict[str, Any]:
        body: dict[str, Any] = {
            "quantity": int(quantity),
            "product": product,
            "validity": validity,
            "price": float(price),
            "tag": tag,
            "instrument_token": instrument_token,
            "order_type": order_type,
            "transaction_type": transaction_type,
            "disclosed_quantity": int(disclosed_quantity),
            "trigger_price": float(trigger_price),
            "is_amo": bool(is_amo),
            "market_protection": int(market_protection),
        }
        status, payload, _ = self._request("POST", PLACE_ORDER_PATH, body=body)
        order_id: str | None = None
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict):
                order_id = data.get("order_id")
        return {
            "status_code": status,
            "response": payload,
            "order_id": str(order_id) if order_id else None,
        }

    def get_order_history(self, order_id: str) -> tuple[int | None, dict | str | None]:
        """Best-effort: order-history is NOT sandbox-enabled yet; raw response is logged."""
        try:
            status, payload, _ = self._request("GET", ORDER_HISTORY_PATH, params={"order_id": order_id})
            return status, payload
        except requests.RequestException as exc:
            logger.warning("order-history poll failed for %s: %s", order_id, exc)
            return None, {"transport_error": str(exc)}

    def get_order_trades(self, order_id: str) -> tuple[int | None, dict | str | None]:
        """Best-effort: order-trades is NOT sandbox-enabled yet; raw response is logged."""
        try:
            status, payload, _ = self._request("GET", ORDER_TRADES_PATH, params={"order_id": order_id})
            return status, payload
        except requests.RequestException as exc:
            logger.warning("order-trades poll failed for %s: %s", order_id, exc)
            return None, {"transport_error": str(exc)}

    def check_auth(self) -> dict[str, Any]:
        """Best-effort auth check (profile endpoint may not be sandbox-enabled)."""
        try:
            status, payload, _ = self._request("GET", PROFILE_PATH)
            return {"status_code": status, "response": payload}
        except requests.RequestException as exc:
            return {"status_code": None, "response": {"transport_error": str(exc)}}
