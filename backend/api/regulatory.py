"""Regulatory control and observability endpoints."""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter

from engines.circuit_breaker import circuit_breaker
from engines.kill_switch import kill_switch
from engines.otr_monitor import otr_monitor
from engines.risk_limits import risk_limits
from ha.journal import journal

router = APIRouter(prefix="/api/regulatory", tags=["regulatory"])


class KillSwitchBody(BaseModel):
    active: bool
    reason: str = "Manual trigger"


@router.get("/circuit-breakers")
async def get_circuit_breakers() -> dict:
    return circuit_breaker.status()


@router.post("/circuit-breakers/{symbol}/reset")
async def reset_circuit_breaker(symbol: str) -> dict:
    circuit_breaker.reset(symbol)
    return {"status": "reset", "symbol": symbol.upper()}


@router.get("/kill-switch")
async def get_kill_switch_status() -> dict:
    return kill_switch.status()


@router.post("/kill-switch")
async def toggle_kill_switch(body: KillSwitchBody) -> dict:
    if body.active:
        kill_switch.activate(reason=body.reason)
        await journal.write("kill_switch", "GLOBAL", {"action": "activate", "reason": body.reason})
    else:
        kill_switch.deactivate()
        await journal.write("kill_switch", "GLOBAL", {"action": "deactivate"})
    return kill_switch.status()


@router.post("/kill-switch/activate")
async def activate_kill_switch(body: KillSwitchBody) -> dict:
    kill_switch.activate(reason=body.reason)
    await journal.write("kill_switch", "GLOBAL", {"action": "activate", "reason": body.reason})
    return {"status": "activated", **kill_switch.status()}


@router.post("/kill-switch/deactivate")
async def deactivate_kill_switch() -> dict:
    kill_switch.deactivate()
    await journal.write("kill_switch", "GLOBAL", {"action": "deactivate"})
    return {"status": "deactivated", **kill_switch.status()}


@router.get("/otr")
async def get_otr_summary() -> dict:
    return otr_monitor.summary()


@router.get("/risk-limits")
async def get_risk_limits() -> dict:
    return risk_limits.status()
