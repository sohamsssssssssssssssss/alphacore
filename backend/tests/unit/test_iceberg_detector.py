from datetime import datetime, timezone, timedelta
from engines.iceberg_detector import IcebergDetector
from models.schemas import OrderBookSnapshot, OrderLevel


def _snap(bids, asks):
    return OrderBookSnapshot(symbol="RELIANCE", timestamp=datetime.now(timezone.utc), bids=bids, asks=asks, spread=1.0, bid_ask_imbalance=0.2, total_bid_volume=sum(x.volume for x in bids), total_ask_volume=sum(x.volume for x in asks))


def _warm(detector, prev, curr, n=3):
    detector.update("RELIANCE", prev)
    out = []
    for i in range(n):
        curr.timestamp = datetime.now(timezone.utc) + timedelta(seconds=i)
        out = detector.update("RELIANCE", curr)
    return out


def test_iceberg_detected_on_consistent_volume():
    d = IcebergDetector()
    prev = _snap([OrderLevel(price=100-i, volume=900) for i in range(5)], [OrderLevel(price=101+i, volume=900) for i in range(5)])
    curr = _snap([OrderLevel(price=100-i, volume=1000) for i in range(5)], [OrderLevel(price=101+i, volume=1000) for i in range(5)])
    assert _warm(d, prev, curr, 4)


def test_no_iceberg_on_random_volume():
    d = IcebergDetector()
    prev = _snap([OrderLevel(price=100-i, volume=v) for i, v in enumerate([100,200,300,400,500])], [OrderLevel(price=101+i, volume=v) for i, v in enumerate([500,400,300,200,100])])
    curr = _snap([OrderLevel(price=100-i, volume=v) for i, v in enumerate([101,195,299,390,480])], [OrderLevel(price=101+i, volume=v) for i, v in enumerate([490,398,280,180,95])])
    out = _warm(d, prev, curr, 1)
    assert out == [] or all(x.confidence_score <= 40 for x in out)


def test_iceberg_has_required_fields(mock_order_book):
    d = IcebergDetector()
    bids = [OrderLevel(**x) for x in mock_order_book["bids"]]
    asks = [OrderLevel(**x) for x in mock_order_book["asks"]]
    out = _warm(d, _snap(bids, asks), _snap(bids, asks), 4)
    for x in out:
        for k in ["symbol", "direction", "price_level", "confidence_score", "refill_count"]:
            assert hasattr(x, k)


def test_iceberg_side_is_buy_or_sell():
    d = IcebergDetector()
    out = _warm(d, _snap([OrderLevel(price=100-i, volume=900) for i in range(5)], [OrderLevel(price=101+i, volume=900) for i in range(5)]), _snap([OrderLevel(price=100-i, volume=1000) for i in range(5)], [OrderLevel(price=101+i, volume=1000) for i in range(5)]), 4)
    assert all(x.direction in ["buy", "sell"] for x in out)


def test_iceberg_confidence_between_0_and_100():
    d = IcebergDetector()
    out = _warm(d, _snap([OrderLevel(price=100-i, volume=900) for i in range(5)], [OrderLevel(price=101+i, volume=900) for i in range(5)]), _snap([OrderLevel(price=100-i, volume=1000) for i in range(5)], [OrderLevel(price=101+i, volume=1000) for i in range(5)]), 4)
    assert all(0 <= x.confidence_score <= 100 for x in out)


def test_iceberg_price_matches_orderbook():
    d = IcebergDetector()
    curr = _snap([OrderLevel(price=100-i, volume=1000) for i in range(5)], [OrderLevel(price=101+i, volume=1000) for i in range(5)])
    out = _warm(d, _snap([OrderLevel(price=100-i, volume=900) for i in range(5)], [OrderLevel(price=101+i, volume=900) for i in range(5)]), curr, 4)
    prices = {x.price for x in curr.bids + curr.asks}
    assert all(x.price_level in prices for x in out)


def test_iceberg_detector_handles_empty_book():
    d = IcebergDetector()
    d.update("RELIANCE", _snap([], []))
    assert d.update("RELIANCE", _snap([], [])) == []


def test_iceberg_detector_handles_single_level():
    d = IcebergDetector()
    d.update("RELIANCE", _snap([OrderLevel(price=100, volume=1)], [OrderLevel(price=101, volume=1)]))
    out = d.update("RELIANCE", _snap([OrderLevel(price=100, volume=2)], [OrderLevel(price=101, volume=2)]))
    assert isinstance(out, list)
