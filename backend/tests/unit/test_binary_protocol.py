from __future__ import annotations

import pytest

from ws.binary_protocol import (
    DETECTION_EVENT,
    HEARTBEAT,
    ORDER_BOOK_SNAPSHOT,
    TRADE_SIGNAL,
    BinaryFrame,
    BinaryProtocol,
    BinaryProtocolError,
)


def test_binary_encode_decode_roundtrip():
    data = BinaryProtocol.encode(TRADE_SIGNAL, {"symbol": "RELIANCE"})
    msg_type, payload = BinaryProtocol.decode(data)
    assert msg_type == TRADE_SIGNAL
    assert payload["symbol"] == "RELIANCE"


def test_binary_magic_bytes_correct():
    frame = BinaryProtocol.encode(HEARTBEAT, {"x": 1})
    assert frame[0] == 0xAC
    assert frame[1] == 0x01


def test_binary_heartbeat_frame():
    frame = BinaryProtocol.heartbeat()
    msg_type, payload = BinaryProtocol.decode(frame)
    assert msg_type == HEARTBEAT
    assert payload["kind"] == "heartbeat"


def test_binary_order_book_snapshot_frame():
    frame = BinaryProtocol.encode(ORDER_BOOK_SNAPSHOT, {"symbol": "TCS"})
    msg_type, payload = BinaryProtocol.decode(frame)
    assert msg_type == ORDER_BOOK_SNAPSHOT
    assert payload["symbol"] == "TCS"


def test_binary_trade_signal_frame():
    frame = BinaryProtocol.encode(TRADE_SIGNAL, {"score": 88})
    msg_type, payload = BinaryProtocol.decode(frame)
    assert msg_type == TRADE_SIGNAL
    assert payload["score"] == 88


def test_binary_detection_event_frame():
    frame = BinaryProtocol.encode(DETECTION_EVENT, {"icebergs": []})
    msg_type, payload = BinaryProtocol.decode(frame)
    assert msg_type == DETECTION_EVENT
    assert payload["icebergs"] == []


def test_binary_bad_magic_raises():
    frame = BinaryProtocol.encode(HEARTBEAT, {})
    bad = bytes([0x00, 0x00]) + frame[2:]
    with pytest.raises(BinaryProtocolError):
        BinaryProtocol.decode(bad)


def test_binary_version_mismatch_raises():
    frame = bytearray(BinaryProtocol.encode(HEARTBEAT, {}))
    frame[2] = 9
    with pytest.raises(BinaryProtocolError):
        BinaryProtocol.decode(bytes(frame))


def test_binary_unpack_length_mismatch_raises():
    frame = BinaryFrame(msg_type=HEARTBEAT, payload=b"abc").pack()
    truncated = frame[:-1]
    with pytest.raises(BinaryProtocolError):
        BinaryProtocol.decode(truncated)
