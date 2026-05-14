"""Custom AlphaCore binary websocket protocol."""

from __future__ import annotations

import json
import struct

MAGIC = 0xAC01
VERSION = 1
HEADER_FMT = ">HBBI"
HEADER_SIZE = struct.calcsize(HEADER_FMT)

ORDER_BOOK_SNAPSHOT = 0x01
TRADE_SIGNAL = 0x02
DETECTION_EVENT = 0x03
HEARTBEAT = 0x04
REGULATORY_ALERT = 0x05


class BinaryProtocolError(ValueError):
    pass


class BinaryFrame:
    def __init__(self, msg_type: int, payload: bytes, version: int = VERSION, magic: int = MAGIC):
        self.magic = magic
        self.version = version
        self.msg_type = msg_type
        self.payload = payload

    def pack(self) -> bytes:
        return struct.pack(HEADER_FMT, self.magic, self.version, self.msg_type, len(self.payload)) + self.payload

    @classmethod
    def unpack(cls, data: bytes) -> "BinaryFrame":
        if len(data) < HEADER_SIZE:
            raise BinaryProtocolError("Frame too short")
        magic, version, msg_type, length = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
        if magic != MAGIC:
            raise BinaryProtocolError("Bad magic")
        if version != VERSION:
            raise BinaryProtocolError("Version mismatch")
        payload = data[HEADER_SIZE:]
        if len(payload) != length:
            raise BinaryProtocolError("Payload length mismatch")
        return cls(msg_type=msg_type, payload=payload, version=version, magic=magic)


class BinaryProtocol:
    @staticmethod
    def encode(msg_type: int, payload: dict) -> bytes:
        payload_bytes = json.dumps(payload, default=str).encode("utf-8")
        return BinaryFrame(msg_type=msg_type, payload=payload_bytes).pack()

    @staticmethod
    def decode(data: bytes) -> tuple[int, dict]:
        frame = BinaryFrame.unpack(data)
        try:
            payload = json.loads(frame.payload.decode("utf-8")) if frame.payload else {}
        except json.JSONDecodeError as exc:
            raise BinaryProtocolError("Invalid JSON payload") from exc
        return frame.msg_type, payload

    @staticmethod
    def heartbeat() -> bytes:
        return BinaryProtocol.encode(HEARTBEAT, {"kind": "heartbeat"})
