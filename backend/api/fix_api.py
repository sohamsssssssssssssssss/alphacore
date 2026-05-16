"""FIX connectivity simulation API endpoints."""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from engines.fix_parser import FIXParseError, FIXParser
from engines.fix_session import fix_session

router = APIRouter(prefix="/api/fix", tags=["fix"])
parser = FIXParser()


class FixRawBody(BaseModel):
    raw: str


class FixOrderBody(BaseModel):
    symbol: str
    side: str
    qty: int
    price: float


@router.post("/parse")
async def parse_fix(body: FixRawBody) -> dict:
    """Parse FIX payload; accepts both `\\x01` and `|` field delimiters."""
    try:
        msg = parser.parse(body.raw)
        return {"msg_type": msg.msg_type, "fields": msg.fields}
    except FIXParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/order")
async def send_fix_order(body: FixOrderBody) -> dict:
    msg = await fix_session.new_order(body.symbol, body.side, body.qty, body.price, "2")
    return {"status": "sent", "msg_type": msg.msg_type, "fields": msg.fields}


@router.get("/session")
async def get_fix_session() -> dict:
    return fix_session.status()


@router.post("/reset")
async def reset_fix_session() -> dict:
    fix_session.reset()
    return {"status": "reset", **fix_session.status()}
