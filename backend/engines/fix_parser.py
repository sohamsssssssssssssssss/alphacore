"""Pure-Python FIX 4.4 parser and encoder."""

from __future__ import annotations

SOH = "\x01"


class FIXParseError(ValueError):
    pass


class FIXMessage:
    def __init__(self, fields: dict[str, str]):
        self.fields = fields

    @property
    def msg_type(self) -> str:
        return self.fields.get("35", "")


class FIXParser:
    SUPPORTED_TYPES = {"D", "8", "V", "W", "X", "A", "5"}

    def parse(self, raw: str) -> FIXMessage:
        if not raw:
            raise FIXParseError("Empty FIX payload")

        # Normalise delimiter (accept raw SOH or pipe-delimited FIX).
        if SOH in raw:
            delimiter = SOH
        elif "|" in raw:
            delimiter = "|"
        else:
            delimiter = SOH
        normalized = raw.replace(delimiter, SOH) if delimiter != SOH else raw

        if not normalized.endswith(SOH):
            raise FIXParseError("FIX message must end with SOH")

        segments = [seg for seg in normalized.split(SOH) if seg]
        fields: dict[str, str] = {}
        for seg in segments:
            if "=" not in seg:
                raise FIXParseError(f"Malformed tag pair: {seg}")
            tag, value = seg.split("=", 1)
            if not tag:
                raise FIXParseError("Missing tag")
            fields[tag] = value

        for required in ("8", "35"):
            if required not in fields:
                raise FIXParseError(f"Missing required tag {required}")

        if fields["35"] not in self.SUPPORTED_TYPES:
            raise FIXParseError(f"Unsupported MsgType {fields['35']}")

        if "10" in fields:
            self._validate_checksum(normalized)
        return FIXMessage(fields)

    @staticmethod
    def _validate_checksum(raw: str) -> None:
        checksum_pos = raw.rfind(f"{SOH}10=")
        if checksum_pos == -1:
            raise FIXParseError("Missing checksum tag")
        payload = raw[: checksum_pos + 1]
        tag10 = raw[checksum_pos + 1 :].strip(SOH)
        try:
            sent_checksum = int(tag10.split("=", 1)[1])
        except Exception as exc:
            raise FIXParseError("Invalid checksum format") from exc

        computed = sum(payload.encode("utf-8")) % 256
        if sent_checksum != computed:
            raise FIXParseError(f"Checksum mismatch: sent={sent_checksum} computed={computed}")


class FIXEncoder:
    @staticmethod
    def encode(fields: dict[str, str]) -> str:
        header = {
            "8": fields.get("8", "FIX.4.4"),
            "9": "000",
        }
        body_fields = {k: str(v) for k, v in fields.items() if k not in {"8", "9", "10"}}
        ordered_tags = ["35", "34", "49", "56", "52", "11", "55", "54", "38", "40", "44", "59", "60"]
        ordered_pairs = []
        for tag in ordered_tags:
            if tag in body_fields:
                ordered_pairs.append((tag, body_fields.pop(tag)))
        ordered_pairs.extend(sorted(body_fields.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 9999))

        body = "".join(f"{k}={v}{SOH}" for k, v in ordered_pairs)
        body_len = len(body.encode("utf-8"))
        pre_checksum = f"8={header['8']}{SOH}9={body_len}{SOH}{body}"
        checksum = sum(pre_checksum.encode("utf-8")) % 256
        return f"{pre_checksum}10={checksum:03d}{SOH}"
