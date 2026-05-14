"""Simulated FIX session state machine."""

from __future__ import annotations

from datetime import datetime, timezone

from engines.fix_parser import FIXEncoder, FIXMessage, FIXParser
from ha.journal import journal


class FIXSessionState:
    DISCONNECTED = "DISCONNECTED"
    LOGON = "LOGON"
    ACTIVE = "ACTIVE"
    LOGOUT = "LOGOUT"


class FIXSession:
    def __init__(self, sender_comp_id: str = "ALPHACORE", target_comp_id: str = "EXCHANGE"):
        self.sender_comp_id = sender_comp_id
        self.target_comp_id = target_comp_id
        self.state = FIXSessionState.DISCONNECTED
        self.out_seq_num = 1
        self.in_seq_num = 1
        self.last_activity_at: str | None = None
        self._parser = FIXParser()

    def _base_fields(self, msg_type: str) -> dict[str, str]:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H:%M:%S")
        return {
            "8": "FIX.4.4",
            "35": msg_type,
            "34": str(self.out_seq_num),
            "49": self.sender_comp_id,
            "56": self.target_comp_id,
            "52": ts,
        }

    async def logon(self) -> FIXMessage:
        self.state = FIXSessionState.LOGON
        fields = self._base_fields("A")
        encoded = FIXEncoder.encode(fields)
        msg = self._parser.parse(encoded)
        await journal.write("fix_sent", "GLOBAL", msg.fields)
        self.out_seq_num += 1
        self.state = FIXSessionState.ACTIVE
        self.last_activity_at = datetime.now(timezone.utc).isoformat()
        return msg

    async def logout(self) -> FIXMessage:
        self.state = FIXSessionState.LOGOUT
        fields = self._base_fields("5")
        encoded = FIXEncoder.encode(fields)
        msg = self._parser.parse(encoded)
        await journal.write("fix_sent", "GLOBAL", msg.fields)
        self.out_seq_num += 1
        self.state = FIXSessionState.DISCONNECTED
        self.last_activity_at = datetime.now(timezone.utc).isoformat()
        return msg

    async def new_order(self, symbol: str, side: str, qty: int, price: float, order_type: str = "2") -> FIXMessage:
        if self.state != FIXSessionState.ACTIVE:
            await self.logon()
        fields = self._base_fields("D")
        fields.update(
            {
                "11": f"ORD{int(datetime.now(timezone.utc).timestamp())}",
                "55": symbol.upper(),
                "54": "1" if side.upper() == "BUY" else "2",
                "38": str(int(qty)),
                "40": order_type,
                "44": f"{float(price):.2f}",
                "60": datetime.now(timezone.utc).strftime("%Y%m%d-%H:%M:%S"),
            }
        )
        encoded = FIXEncoder.encode(fields)
        msg = self._parser.parse(encoded)
        await journal.write("fix_sent", symbol.upper(), msg.fields)
        self.out_seq_num += 1
        self.last_activity_at = datetime.now(timezone.utc).isoformat()
        return msg

    async def process_execution_report(self, msg: FIXMessage) -> dict:
        if msg.msg_type != "8":
            return {"ok": False, "reason": "Not an execution report"}
        await journal.write("fix_received", msg.fields.get("55", "GLOBAL"), msg.fields)
        self.in_seq_num = max(self.in_seq_num, int(msg.fields.get("34", self.in_seq_num)) + 1)
        self.last_activity_at = datetime.now(timezone.utc).isoformat()
        return {
            "ok": True,
            "symbol": msg.fields.get("55"),
            "order_id": msg.fields.get("37"),
            "exec_type": msg.fields.get("150"),
            "ord_status": msg.fields.get("39"),
            "last_qty": msg.fields.get("32"),
            "last_px": msg.fields.get("31"),
        }

    def reset(self) -> None:
        self.out_seq_num = 1
        self.in_seq_num = 1
        self.state = FIXSessionState.DISCONNECTED
        self.last_activity_at = None

    def status(self) -> dict:
        return {
            "state": self.state,
            "sender_comp_id": self.sender_comp_id,
            "target_comp_id": self.target_comp_id,
            "out_seq_num": self.out_seq_num,
            "in_seq_num": self.in_seq_num,
            "last_activity_at": self.last_activity_at,
        }


fix_session = FIXSession()
