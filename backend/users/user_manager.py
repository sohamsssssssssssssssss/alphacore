from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from execution.paper_engine import PaperTradingEngine
from risk.risk_manager import RiskGate


class SubscriptionTier(str, Enum):
    FREE = "FREE"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"


@dataclass
class UserAccount:
    id: str
    name: str
    capital: float
    risk_limits: dict
    strategy_config: dict
    kill_switch: bool
    tier: SubscriptionTier


class UserManager:
    DEFAULT_RISK_LIMITS = {
        "max_position": 50000,
        "daily_loss": 5000,
        "drawdown_pct": 5.0,
        "order_rate": 10,
        "concentration": 0.3,
    }

    def __init__(self, db_url: str | None = None):
        resolved = db_url or os.getenv("ALPHACORE_USERS_DB") or "postgresql://localhost/alphacore"
        self.db_url = resolved
        self.engine: Engine = sa.create_engine(self.db_url, future=True)
        self._risk_gates: dict[str, RiskGate] = {}
        self._paper_engines: dict[str, PaperTradingEngine] = {}
        self._init_schema()

    def _init_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                sa.text(
                    """
                    CREATE TABLE IF NOT EXISTS user_accounts (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        capital NUMERIC NOT NULL,
                        risk_limits TEXT NOT NULL,
                        strategy_config TEXT NOT NULL,
                        kill_switch BOOLEAN NOT NULL,
                        tier TEXT NOT NULL
                    )
                    """
                )
            )

    @staticmethod
    def _row_to_user(row) -> UserAccount:
        return UserAccount(
            id=str(row["id"]),
            name=str(row["name"]),
            capital=float(row["capital"]),
            risk_limits=json.loads(str(row["risk_limits"])),
            strategy_config=json.loads(str(row["strategy_config"])),
            kill_switch=bool(row["kill_switch"]),
            tier=SubscriptionTier(str(row["tier"])),
        )

    def create_user(
        self,
        id: str,
        name: str,
        capital: float,
        tier: SubscriptionTier = SubscriptionTier.FREE,
        risk_limits: dict | None = None,
    ) -> UserAccount:
        with self.engine.begin() as conn:
            exists = conn.execute(sa.text("SELECT 1 FROM user_accounts WHERE id = :id"), {"id": id}).scalar_one_or_none()
            if exists is not None:
                raise ValueError(f"user id already exists: {id}")

            limits = dict(self.DEFAULT_RISK_LIMITS)
            if risk_limits:
                limits.update(risk_limits)

            strategy_config = {}
            conn.execute(
                sa.text(
                    """
                    INSERT INTO user_accounts (id, name, capital, risk_limits, strategy_config, kill_switch, tier)
                    VALUES (:id, :name, :capital, :risk_limits, :strategy_config, :kill_switch, :tier)
                    """
                ),
                {
                    "id": id,
                    "name": name,
                    "capital": float(capital),
                    "risk_limits": json.dumps(limits),
                    "strategy_config": json.dumps(strategy_config),
                    "kill_switch": False,
                    "tier": SubscriptionTier(tier).value,
                },
            )

        return UserAccount(
            id=id,
            name=name,
            capital=float(capital),
            risk_limits=limits,
            strategy_config=strategy_config,
            kill_switch=False,
            tier=SubscriptionTier(tier),
        )

    def get_user(self, user_id: str) -> UserAccount:
        with self.engine.connect() as conn:
            row = conn.execute(sa.text("SELECT * FROM user_accounts WHERE id = :id"), {"id": user_id}).mappings().first()
        if row is None:
            raise KeyError(user_id)
        return self._row_to_user(row)

    def set_kill_switch(self, user_id: str, active: bool) -> None:
        with self.engine.begin() as conn:
            res = conn.execute(
                sa.text("UPDATE user_accounts SET kill_switch = :active WHERE id = :id"),
                {"active": bool(active), "id": user_id},
            )
            if res.rowcount == 0:
                raise KeyError(user_id)

    def check_subscription(self, user_id: str) -> bool:
        user = self.get_user(user_id)
        return user.tier != SubscriptionTier.FREE

    def list_users(self) -> list[UserAccount]:
        with self.engine.connect() as conn:
            rows = conn.execute(sa.text("SELECT * FROM user_accounts ORDER BY id ASC")).mappings().all()
        return [self._row_to_user(r) for r in rows]

    def get_risk_gate(self, user_id: str) -> RiskGate:
        user = self.get_user(user_id)
        if user.kill_switch:
            raise RuntimeError(f"kill switch active for user: {user_id}")

        if user_id not in self._risk_gates:
            limits = user.risk_limits
            self._risk_gates[user_id] = RiskGate(
                max_position_inr=float(limits.get("max_position", 50000)),
                max_daily_loss=float(limits.get("daily_loss", 5000)),
                max_drawdown_pct=float(limits.get("drawdown_pct", 5.0)) / 100.0,
                max_order_rate_per_min=int(limits.get("order_rate", 10)),
                max_concentration_pct=float(limits.get("concentration", 0.3)),
                starting_capital=float(user.capital),
            )
        return self._risk_gates[user_id]

    def get_paper_engine(self, user_id: str) -> PaperTradingEngine:
        user = self.get_user(user_id)
        if user.kill_switch:
            raise RuntimeError(f"kill switch active for user: {user_id}")

        if user_id not in self._paper_engines:
            self._paper_engines[user_id] = PaperTradingEngine(starting_capital=float(user.capital))
        return self._paper_engines[user_id]
