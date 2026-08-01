"""Token storage and expiry handling for the Upstox sandbox harness.

Upstox sandbox tokens are static 30-day bearer tokens with NO refresh flow
(verified against the sandbox docs). This module therefore implements:
  - storage of both the sandbox token and the read-only market-data token
  - expiry detection with loud alerts
  - HOT RELOAD: if the tokens file (or .env) changes, the new token is picked
    up on the next cycle without restarting the scheduler.

Populate tokens either via .env (backend/paper_trading/.env) or by writing
states/paper_trading/tokens.json while the scheduler is running.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config


@dataclass
class Tokens:
    sandbox_token: str = ""
    marketdata_token: str = ""
    sandbox_expires_at: float | None = None      # unix ts, if known
    marketdata_expires_at: float | None = None
    _sources: dict = field(default_factory=dict)

    def is_expired(self, token: str, expires_at: float | None) -> bool:
        if not token:
            return True
        if expires_at is None:
            return False
        return time.time() >= expires_at

    def sandbox_ok(self) -> bool:
        return bool(self.sandbox_token) and not self.is_expired(
            self.sandbox_token, self.sandbox_expires_at)

    def marketdata_ok(self) -> bool:
        return bool(self.marketdata_token) and not self.is_expired(
            self.marketdata_token, self.marketdata_expires_at)

    def days_left(self) -> float | None:
        if self.sandbox_expires_at is None:
            return None
        return (self.sandbox_expires_at - time.time()) / 86400.0


def _parse_expiry(raw: str | None) -> float | None:
    if not raw:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


class TokenStore:
    """Loads tokens from .env first, then from the JSON tokens file.

    Precedence: .env > tokens.json, so .env is the authoritative source and
    tokens.json is the hot-reload escape hatch. mtime of tokens.json is tracked
    so the scheduler can reload without restarting.
    """

    def __init__(self, tokens_file: Path | None = None):
        self.tokens_file = Path(tokens_file or config.TOKENS_FILE)
        self._file_mtime: float = 0.0
        self._last_error: str | None = None
        self.tokens = self._load()

    def _load_from_env(self) -> dict:
        return {
            "sandbox_token": config.get_env("PAPER_SANDBOX_TOKEN", "") or "",
            "marketdata_token": config.get_env("PAPER_MARKETDATA_TOKEN", "") or "",
            "sandbox_expires_at": _parse_expiry(config.get_env("PAPER_SANDBOX_TOKEN_EXPIRY")),
            "marketdata_expires_at": _parse_expiry(config.get_env("PAPER_MARKETDATA_TOKEN_EXPIRY")),
        }

    def _load(self) -> Tokens:
        env_t = self._load_from_env()
        tok = Tokens(
            sandbox_token=env_t["sandbox_token"],
            marketdata_token=env_t["marketdata_token"],
            sandbox_expires_at=env_t["sandbox_expires_at"],
            marketdata_expires_at=env_t["marketdata_expires_at"],
        )
        self._sources = {"sandbox": "env", "marketdata": "env"}
        try:
            if self.tokens_file.exists():
                data = json.loads(self.tokens_file.read_text())
                # File values override env only when env is empty for that field.
                if not tok.sandbox_token:
                    tok.sandbox_token = str(data.get("sandbox_token", ""))
                    tok.sandbox_expires_at = _parse_expiry(
                        data.get("sandbox_token_expires_at"))
                    self._sources["sandbox"] = "tokens.json"
                if not tok.marketdata_token:
                    tok.marketdata_token = str(data.get("marketdata_token", ""))
                    tok.marketdata_expires_at = _parse_expiry(
                        data.get("marketdata_token_expires_at"))
                    self._sources["marketdata"] = "tokens.json"
                self._file_mtime = self.tokens_file.stat().st_mtime
        except Exception as exc:  # noqa: BLE001 — never crash the scheduler
            self._last_error = f"tokens.json unreadable: {exc}"
        return tok

    def reload_if_changed(self) -> bool:
        """Reload from disk if the tokens file changed. Returns True if reloaded."""
        try:
            if self.tokens_file.exists():
                mtime = self.tokens_file.stat().st_mtime
                if mtime != self._file_mtime:
                    self.tokens = self._load()
                    self._file_mtime = mtime
                    return True
        except OSError:
            pass
        return False

    def health(self) -> dict:
        """Summary for the status script."""
        tok = self.tokens
        return {
            "sandbox_token_set": bool(tok.sandbox_token),
            "sandbox_token_expired": not tok.sandbox_ok(),
            "sandbox_days_left": tok.days_left(),
            "marketdata_token_set": bool(tok.marketdata_token),
            "marketdata_token_expired": not tok.marketdata_ok(),
            "sources": self._sources,
            "last_error": self._last_error,
        }
