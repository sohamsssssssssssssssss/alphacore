from engines.spoof_detector import SpoofDetector


def test_spoof_detector_initial_update_returns_empty(sample_snapshot):
    detector = SpoofDetector()
    assert detector.update("RELIANCE", sample_snapshot) == []
