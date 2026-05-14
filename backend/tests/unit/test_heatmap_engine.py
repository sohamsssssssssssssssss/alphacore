from engines.heatmap_engine import heatmap_engine


def test_heatmap_engine_exposes_builder():
    assert hasattr(heatmap_engine, "update") or hasattr(heatmap_engine, "get_heatmap")
