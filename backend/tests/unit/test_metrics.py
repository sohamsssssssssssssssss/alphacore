from metrics import ACTIVE_SIGNALS, DETECTIONS_TOTAL, ORDER_BOOK_UPDATES, SIGNALS_TOTAL


def test_metrics_objects_exist():
    assert DETECTIONS_TOTAL is not None
    assert SIGNALS_TOTAL is not None
    assert ACTIVE_SIGNALS is not None
    assert ORDER_BOOK_UPDATES is not None
