from __future__ import annotations

import pytest

from engines.fix_parser import FIXEncoder, FIXParseError, FIXParser
from engines.fix_session import FIXSession, FIXSessionState


def _encode(fields: dict[str, str]) -> str:
    payload = {"8": "FIX.4.4", **fields}
    return FIXEncoder.encode(payload)


def test_fix_parse_new_order_single():
    parser = FIXParser()
    raw = _encode({"35": "D", "34": "1", "49": "A", "56": "B", "11": "ORD1", "55": "RELIANCE", "54": "1", "38": "100", "40": "2", "44": "2500.00"})
    msg = parser.parse(raw)
    assert msg.msg_type == "D"
    assert msg.fields["55"] == "RELIANCE"


def test_fix_parse_execution_report():
    parser = FIXParser()
    raw = _encode({"35": "8", "34": "2", "49": "B", "56": "A", "37": "EX1", "39": "2", "150": "F", "55": "TCS"})
    msg = parser.parse(raw)
    assert msg.msg_type == "8"
    assert msg.fields["39"] == "2"


def test_fix_parse_market_data_snapshot():
    parser = FIXParser()
    raw = _encode({"35": "W", "34": "3", "49": "B", "56": "A", "55": "INFY"})
    msg = parser.parse(raw)
    assert msg.msg_type == "W"


def test_fix_checksum_valid():
    parser = FIXParser()
    raw = _encode({"35": "V", "34": "4", "49": "A", "56": "B"})
    msg = parser.parse(raw)
    assert msg.fields["10"].isdigit()


def test_fix_checksum_invalid_raises():
    parser = FIXParser()
    raw = _encode({"35": "X", "34": "5", "49": "A", "56": "B"})
    bad = raw.replace(raw.split("10=")[1][:3], "000", 1)
    with pytest.raises(FIXParseError):
        parser.parse(bad)


def test_fix_encoder_roundtrip():
    parser = FIXParser()
    fields = {"8": "FIX.4.4", "35": "D", "34": "1", "49": "ALPHACORE", "56": "EXCHANGE", "55": "RELIANCE", "54": "1", "38": "100", "40": "2", "44": "2500.00"}
    encoded = FIXEncoder.encode(fields)
    msg = parser.parse(encoded)
    assert msg.fields["35"] == "D"
    assert msg.fields["49"] == "ALPHACORE"


@pytest.mark.asyncio
async def test_fix_session_logon_sequence():
    session = FIXSession()
    msg = await session.logon()
    assert msg.msg_type == "A"
    assert session.state == FIXSessionState.ACTIVE


@pytest.mark.asyncio
async def test_fix_session_new_order_fields():
    session = FIXSession()
    msg = await session.new_order("RELIANCE", "BUY", 100, 2500.0, "2")
    assert msg.fields["35"] == "D"
    assert msg.fields["55"] == "RELIANCE"
    assert msg.fields["54"] == "1"


@pytest.mark.asyncio
async def test_fix_session_seq_increment():
    session = FIXSession()
    start = session.out_seq_num
    await session.logon()
    await session.new_order("TCS", "SELL", 10, 3200.0, "2")
    assert session.out_seq_num >= start + 2


def test_fix_parse_error_on_malformed():
    parser = FIXParser()
    with pytest.raises(FIXParseError):
        parser.parse("8=FIX.4.4\x019=12\x0135=D\x01BAD\x0110=001\x01")


def test_fix_parser_accepts_pipe_delimiter():
    parser = FIXParser()
    raw = _encode({"35": "W", "34": "1", "49": "A", "56": "B", "55": "RELIANCE"}).replace("\x01", "|")
    msg = parser.parse(raw)
    assert msg.msg_type == "W"
